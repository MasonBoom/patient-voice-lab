from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from livekit import agents, api
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    RunContext,
    function_tool,
    inference,
    llm,
    room_io,
)
from livekit.plugins import silero

from .config import AGENT_NAME, SIP_IDENTITY, TEST_NUMBER, Settings, run_directory
from .evidence import persist_session, read_json, write_json
from .scenarios import build_prompt, get_scenario, load_profile

logger = logging.getLogger("voice_probe")


@dataclass
class CallState:
    directory: Path
    settings: Settings
    session: AgentSession | None = None
    ended: asyncio.Event = field(default_factory=asyncio.Event)
    end_reason: str = "remote_hangup"
    error: str | None = None
    last_activity: float = field(default_factory=time.monotonic)
    receptionist_seen: bool = False
    patient_turns: int = 0
    receptionist_turns: int = 0
    interruption_attempted: bool = False
    background: set[asyncio.Task] = field(default_factory=set)

    def task(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    def end(self, reason: str) -> None:
        if not self.ended.is_set():
            self.end_reason = reason
            self.ended.set()


class Patient(Agent):
    def __init__(self, instructions: str, state: CallState):
        super().__init__(instructions=instructions)
        self.state = state

    @function_tool
    async def finish_call(self, context: RunContext, outcome: str) -> str:
        """Finish after the conversation is resolved and you have said goodbye.

        Args:
            outcome: A short, factual summary of what was accomplished or left pending.
        """
        if not self.state.receptionist_seen or self.state.patient_turns < 2:
            return "Do not end yet. Respond to the receptionist and establish a clear next step."

        async def finish_after_playout() -> None:
            # Wait for the CURRENT speech handle; avoid waiting on the tool's own result.
            try:
                await asyncio.wait_for(context.wait_for_playout(), timeout=12)
            except TimeoutError:
                logger.warning("Timed out waiting for final speech playout")
            write_json(self.state.directory / "outcome.json", {"summary": outcome})
            self.state.end("goal_resolved")

        self.state.task(finish_after_playout())
        return "The call will end after your current farewell is heard. Do not speak again."


def setup_process(proc: agents.JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(
    num_idle_processes=1,
    load_threshold=1.0,
    initialize_process_timeout=60,
    shutdown_process_timeout=45,
    session_end_timeout=60,
    host="127.0.0.1",
    port=int(os.environ.get("VOICE_PROBE_WORKER_PORT", "8081")),
    multiprocessing_context="spawn",
    setup_fnc=setup_process,
)


async def save_after_session(ctx: agents.JobContext) -> None:
    state: CallState | None = ctx.proc.userdata.get("call_state")
    if state is None:
        return
    try:
        if state.session is not None:
            report = ctx.make_session_report(state.session)
            await asyncio.to_thread(persist_session, state.directory, report)
        else:
            raise ValueError("No agent session was established.")
        write_json(
            state.directory / "status.json",
            {
                "status": "failed" if state.error else "complete",
                "end_reason": state.end_reason,
                "error": state.error,
            },
        )
    except Exception as exc:
        logger.exception("Unable to finalize call evidence")
        write_json(
            state.directory / "status.json",
            {
                "status": "failed",
                "end_reason": state.end_reason,
                "error": f"Evidence finalization failed: {type(exc).__name__}: {exc}",
            },
        )


async def watch_call(state: CallState) -> None:
    start = time.monotonic()
    prompted = False
    while not state.ended.is_set():
        await asyncio.sleep(1)
        elapsed = time.monotonic() - start
        if elapsed >= state.settings.max_call_seconds:
            state.end("max_duration")
        elif not state.receptionist_seen and elapsed > 20:
            state.end("no_greeting")
        elif not state.receptionist_seen and elapsed > 8 and not prompted:
            # One polite check if the far end answered silently; do not read the scenario.
            prompted = True
            state.session.say("Hello, can you hear me?")
        elif state.receptionist_seen:
            idle = time.monotonic() - state.last_activity
            if idle > state.settings.silence_timeout:
                state.end("silence_timeout")
            elif idle > 15 and not prompted and state.session:
                prompted = True
                state.session.say("Hello, are you still there?")


@server.rtc_session(agent_name=AGENT_NAME, on_session_end=save_after_session)
async def entrypoint(ctx: agents.JobContext) -> None:
    settings = Settings.load()
    settings.validate()
    metadata = json.loads(ctx.job.metadata or "{}")
    scenario = get_scenario(metadata["scenario_id"])
    directory = run_directory(settings.artifacts_dir, metadata["run_id"])
    if not (directory / "call.json").is_file():
        raise ValueError("Run must be initialized by the local runner before dispatch.")
    state = CallState(directory=directory, settings=settings)
    ctx.proc.userdata["call_state"] = state

    async def stop_background() -> None:
        for task in list(state.background):
            task.cancel()
        if state.background:
            await asyncio.gather(*list(state.background), return_exceptions=True)

    ctx.add_shutdown_callback(stop_background)
    try:
        profile = load_profile(settings.profile_path)
        await ctx.connect()
        session = AgentSession(
            stt=inference.STT(model=settings.stt_model, language="en"),
            llm=inference.LLM(
                model=settings.llm_model,
                reasoning=settings.reasoning_effort,
                extra_kwargs={"max_completion_tokens": 300},
            ),
            tts=inference.TTS(
                model=settings.tts_model,
                voice=settings.tts_voice,
                language="en",
            ),
            vad=ctx.proc.userdata["vad"],
            turn_handling={
                "turn_detection": inference.TurnDetector(version="v1-mini")
                if settings.turn_detection == "semantic"
                else "vad",
                "endpointing": {
                    "min_delay": settings.min_endpoint_delay,
                    "max_delay": settings.max_endpoint_delay,
                },
                "interruption": {
                    "enabled": True,
                    "mode": "vad",
                    "min_duration": 0.5,
                    "min_words": 2,
                    "discard_audio_if_uninterruptible": False,
                    "resume_false_interruption": True,
                    "false_interruption_timeout": 1.5,
                },
                "preemptive_generation": {"enabled": False},
            },
            user_away_timeout=None,
        )
        state.session = session

        @session.on("conversation_item_added")
        def on_item(event) -> None:
            item = event.item
            if not isinstance(item, llm.ChatMessage):
                return
            state.last_activity = time.monotonic()
            if item.role == "user":
                state.receptionist_seen = True
                state.receptionist_turns += 1
            elif item.role == "assistant":
                state.patient_turns += 1

        @session.on("user_state_changed")
        def on_user_state(event) -> None:
            state.last_activity = time.monotonic()
            if (
                scenario.get("interruption")
                and event.new_state == "speaking"
                and state.patient_turns >= 1
                and state.receptionist_turns >= 1
                and not state.interruption_attempted
            ):
                state.interruption_attempted = True

                async def interrupt_once() -> None:
                    await asyncio.sleep(1.0)
                    if not state.ended.is_set() and session.user_state == "speaking":
                        # Explicit barge-in test only. Disable interruption of this short
                        # correction so continuing far-end audio does not erase the probe.
                        session.interrupt()
                        await session.say(scenario["interruption"], allow_interruptions=False)
                        write_json(
                            directory / "interruption.json",
                            {
                                "attempted": True,
                                "spoken": True,
                                "text": scenario["interruption"],
                                "at": time.time(),
                            },
                        )
                    else:
                        write_json(
                            directory / "interruption.json",
                            {
                                "attempted": True,
                                "spoken": False,
                                "reason": "Far end stopped before the scheduled interruption.",
                            },
                        )

                state.task(interrupt_once())

        @session.on("agent_state_changed")
        def on_agent_state(_event) -> None:
            state.last_activity = time.monotonic()

        @session.on("close")
        def on_close(_event) -> None:
            state.end("remote_hangup")

        @session.on("error")
        def on_error(event) -> None:
            if not getattr(event.error, "recoverable", False):
                state.error = f"Voice pipeline error: {type(event.error).__name__}"
                state.end("error")

        await session.start(
            agent=Patient(build_prompt(scenario, profile, settings), state),
            room=ctx.room,
            room_options=room_io.RoomOptions(
                participant_identity=SIP_IDENTITY,
                close_on_disconnect=True,
            ),
            record=True,
        )
        write_json(directory / "status.json", {"status": "dialing"})
        # The destination is a constant. Job metadata and the language model cannot choose it.
        participant = await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=settings.trunk_id,
                sip_call_to=TEST_NUMBER,
                sip_number=settings.caller_id,
                room_name=ctx.room.name,
                participant_identity=SIP_IDENTITY,
                participant_name="Assessment test receptionist",
                wait_until_answered=True,
                ringing_timeout=timedelta(seconds=45),
                max_call_duration=timedelta(seconds=settings.max_call_seconds + 10),
                krisp_enabled=True,
            )
        )
        call = read_json(directory / "call.json")
        call.update(
            {
                "answered_at": time.time(),
                "sip_call_id": participant.sip_call_id,
                "sip_participant_id": participant.participant_id,
            }
        )
        write_json(directory / "call.json", call)
        state.last_activity = time.monotonic()
        write_json(directory / "status.json", {"status": "active"})
        # There is deliberately no generated greeting here: the receptionist speaks first.
        state.task(watch_call(state))
        await state.ended.wait()
    except Exception as exc:
        state.error = f"{type(exc).__name__}: {exc}"
        state.end("error")
        logger.exception("Call failed")
    finally:
        await stop_background()
        if state.session:
            await state.session.aclose()
        # DeleteRoom also hangs up the SIP participant; this covers timeout and failed jobs.
        try:
            await ctx.api.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))
        except Exception:
            logger.warning("Room cleanup failed; runner will try again", exc_info=True)
        ctx.shutdown(reason=state.end_reason)


if __name__ == "__main__":
    agents.cli.run_app(server)
