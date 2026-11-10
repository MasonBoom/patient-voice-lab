from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from voice_probe.config import SIP_IDENTITY, TEST_NUMBER
from voice_probe.evidence import read_json, write_json
from voice_probe.scenarios import get_scenario


def fake_job(settings, monkeypatch, *, dial_fails=False):
    from voice_probe import worker

    run_id = "20261109T120000Z-0123456789"
    directory = settings.artifacts_dir / run_id
    write_json(directory / "call.json", {"scenario": get_scenario("01-schedule")})
    order = []

    class FakeSession:
        def __init__(self):
            self.handlers = {}
            self.user_state = "listening"

        def on(self, event):
            def register(callback):
                self.handlers[event] = callback
                return callback

            return register

        async def start(self, **kwargs):
            assert kwargs["record"] is True
            assert kwargs["room_options"].participant_identity == SIP_IDENTITY
            order.append("recording_and_listening_started")

        async def aclose(self):
            order.append("session_closed")

    session = FakeSession()

    async def dial(request):
        order.append("sip_dial")
        assert request.sip_call_to == TEST_NUMBER
        assert request.sip_number == settings.caller_id
        assert request.participant_identity == SIP_IDENTITY
        assert request.wait_until_answered is True
        if dial_fails:
            raise RuntimeError("provider refused the request")
        asyncio.get_running_loop().call_soon(session.handlers["close"], SimpleNamespace())
        return SimpleNamespace(sip_call_id="test-sip-id", participant_id="test-participant")

    async def delete_room(_request):
        order.append("phone_room_deleted")

    ctx = SimpleNamespace(
        proc=SimpleNamespace(userdata={"vad": object()}),
        job=SimpleNamespace(
            metadata=json.dumps(
                {
                    "scenario_id": "01-schedule",
                    "run_id": run_id,
                    # A job trying to override the number must have no effect on routing.
                    "phone_number": "+15555550999",
                }
            )
        ),
        room=SimpleNamespace(name="test-room"),
        api=SimpleNamespace(
            sip=SimpleNamespace(create_sip_participant=AsyncMock(side_effect=dial)),
            room=SimpleNamespace(delete_room=AsyncMock(side_effect=delete_room)),
        ),
        connect=AsyncMock(),
        add_shutdown_callback=Mock(),
        shutdown=Mock(),
    )
    monkeypatch.setattr(worker.Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(worker, "AgentSession", lambda **kwargs: session)
    for name in ("STT", "LLM", "TTS"):
        monkeypatch.setattr(worker.inference, name, lambda **kwargs: object())
    return worker, ctx, directory, order


def test_listening_and_recording_start_before_fixed_destination_is_dialed(settings, monkeypatch):
    worker, ctx, directory, order = fake_job(settings, monkeypatch)
    asyncio.run(worker.entrypoint(ctx))
    assert order == [
        "recording_and_listening_started",
        "sip_dial",
        "session_closed",
        "phone_room_deleted",
    ]
    assert read_json(directory / "call.json")["sip_call_id"] == "test-sip-id"
    ctx.shutdown.assert_called_once_with(reason="remote_hangup")


def test_failed_sip_dial_closes_session_and_hangs_up_room(settings, monkeypatch):
    worker, ctx, directory, order = fake_job(settings, monkeypatch, dial_fails=True)
    asyncio.run(worker.entrypoint(ctx))
    assert order[-2:] == ["session_closed", "phone_room_deleted"]
    state = ctx.proc.userdata["call_state"]
    assert "provider refused" in state.error
    ctx.shutdown.assert_called_once_with(reason="error")


def test_save_callback_does_not_claim_success_when_recording_is_missing(settings, monkeypatch):
    from voice_probe import worker

    state = worker.CallState(directory=settings.artifacts_dir / "test-run", settings=settings)
    state.session = object()
    report = SimpleNamespace(
        audio_recording_started_at=100,
        audio_recording_path=None,
        chat_history=SimpleNamespace(items=[]),
        to_dict=lambda: {},
    )
    ctx = SimpleNamespace(
        proc=SimpleNamespace(userdata={"call_state": state}),
        make_session_report=lambda session: report,
    )
    asyncio.run(worker.save_after_session(ctx))
    status = read_json(state.directory / "status.json")
    assert status["status"] == "failed"
    assert "did not produce an audio recording" in status["error"]


def test_actual_sdk_accepts_separate_pipeline_and_turn_options(monkeypatch):
    """Construct real SDK adapters without invoking any model or phone service."""
    from livekit.agents import AgentSession, inference

    monkeypatch.setenv("LIVEKIT_API_KEY", "offline-test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "offline-test-secret-32-characters-minimum")
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    for name in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
    ):
        monkeypatch.delenv(name, raising=False)

    async def construct():
        stt = inference.STT(model="deepgram/nova-3", language="en")
        llm = inference.LLM(
            model="openai/gpt-5.4-mini",
            reasoning="none",
            extra_kwargs={"max_completion_tokens": 300},
        )
        tts = inference.TTS(
            model="cartesia/sonic-3",
            voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
            language="en",
        )
        try:
            session = AgentSession(
                stt=stt,
                llm=llm,
                tts=tts,
                turn_handling={
                    "turn_detection": "vad",
                    "endpointing": {"min_delay": 0.65, "max_delay": 3.0},
                    "interruption": {
                        "enabled": True,
                        "mode": "vad",
                        "min_words": 2,
                        "discard_audio_if_uninterruptible": False,
                    },
                    "preemptive_generation": {"enabled": False},
                },
                user_away_timeout=None,
            )
            assert session.stt is stt and session.llm is llm and session.tts is tts
        finally:
            await stt.aclose()
            await llm.aclose()
            await tts.aclose()

    asyncio.run(construct())
