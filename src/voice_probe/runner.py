from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from livekit import api

from .config import AGENT_NAME, TEST_NUMBER, Settings, run_directory, validate_destination
from .evidence import build_index, call_directories, read_json, technical_issues, write_json
from .scenarios import load_profile


def client(settings: Settings) -> api.LiveKitAPI:
    return api.LiveKitAPI(settings.url, settings.api_key, settings.api_secret)


async def verify_trunk(settings: Settings, livekit) -> None:
    response = await livekit.sip.list_sip_outbound_trunk(api.ListSIPOutboundTrunkRequest())
    trunk = next((t for t in response.items if t.sip_trunk_id == settings.trunk_id), None)
    if trunk is None:
        raise ValueError("SIP_OUTBOUND_TRUNK_ID is not an outbound trunk in this LiveKit project.")
    if settings.caller_id not in trunk.numbers:
        raise ValueError("CALLER_ID is not one of this outbound trunk's configured numbers.")


def enforce_single_caller(root: Path, caller_id: str) -> None:
    for directory in call_directories(root):
        previous = read_json(directory / "call.json").get("caller_id")
        if previous != caller_id:
            raise ValueError(
                "Existing call evidence used another caller ID. Use the same outbound number "
                "for the entire assessment; do not mix numbers."
            )
    identity_file = root / "caller.json"
    if identity_file.exists() and read_json(identity_file).get("caller_id") != caller_id:
        raise ValueError("CALLER_ID differs from the number already locked for this assessment.")
    write_json(identity_file, {"caller_id": caller_id, "destination": TEST_NUMBER})


@contextmanager
def batch_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".run-lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            "Another batch is running. If a process crashed, confirm it is stopped before "
            "removing artifacts/.run-lock."
        ) from exc
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def worker_healthy(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
            return response.status == 200 and response.read(10) == b"OK"
    except (URLError, OSError):
        return False


@contextlib.asynccontextmanager
async def local_worker(settings: Settings):
    port = free_port()
    log_path = settings.artifacts_dir / f"worker-{int(time.time())}.log"
    environment = dict(os.environ, VOICE_PROBE_WORKER_PORT=str(port))
    process = None
    with log_path.open("w", encoding="utf-8") as log:
        try:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [sys.executable, "-m", "voice_probe.worker", "start"],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            print("Starting local LiveKit worker...", flush=True)
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError(f"Worker stopped unexpectedly; inspect {log_path}.")
                if await asyncio.to_thread(worker_healthy, port):
                    break
                await asyncio.sleep(1)
            else:
                raise TimeoutError(f"Worker did not connect within 120s; inspect {log_path}.")
            yield process
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, timeout=45)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, timeout=5)


async def execute_call(settings: Settings, livekit, scenario: dict, worker) -> Path:
    validate_destination(TEST_NUMBER)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:10]
    directory = run_directory(settings.artifacts_dir, run_id)
    directory.mkdir(parents=True)
    room_name = f"patient-test-{run_id}"
    write_json(
        directory / "call.json",
        {
            "run_id": run_id,
            "scenario": scenario,
            "caller_id": settings.caller_id,
            "destination": TEST_NUMBER,
            "room": room_name,
            "created_at": time.time(),
            "answered_at": None,
            "models": {
                "stt": settings.stt_model,
                "llm": settings.llm_model,
                "tts": settings.tts_model,
            },
            "turn_detection": settings.turn_detection,
            "sdk_version": "1.8.11",
        },
    )
    write_json(directory / "status.json", {"status": "dispatching"})
    try:
        await livekit.room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                empty_timeout=60,
                departure_timeout=20,
            )
        )
        await livekit.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room_name,
                metadata=json.dumps({"run_id": run_id, "scenario_id": scenario["id"]}),
            )
        )
        # Covers startup, ringing, call limit, and post-session evidence finalization.
        deadline = time.monotonic() + settings.max_call_seconds + 180
        while time.monotonic() < deadline:
            status = read_json(directory / "status.json")
            if status["status"] in {"complete", "failed"}:
                return directory
            if worker.poll() is not None:
                raise RuntimeError("Worker exited during the call.")
            await asyncio.sleep(1)
        raise TimeoutError("No final report received before the run deadline.")
    except BaseException as exc:
        write_json(
            directory / "status.json",
            {
                "status": "failed",
                "end_reason": "error",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        raise
    finally:
        # Cancellation, Ctrl+C, and worker crashes also terminate the phone connection.
        try:
            await livekit.room.delete_room(api.DeleteRoomRequest(room=room_name))
        except Exception:
            pass  # Worker may already have deleted it; SIP also has a server-side limit.


async def run_batch(
    settings: Settings, selected: list[dict], *, resume: bool = False
) -> list[Path]:
    settings.validate()
    profile = load_profile(settings.profile_path)
    if profile.get("test_account_created") is not True:
        raise ValueError(
            "Create the assessment test account, match practice-profile.json to it, "
            "then set test_account_created to true before making calls."
        )
    if not 1 <= len(selected) <= 12:
        raise ValueError("A batch must contain between one and twelve scenarios.")
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    with batch_lock(settings.artifacts_dir):
        enforce_single_caller(settings.artifacts_dir, settings.caller_id)
        if resume:
            completed = {
                read_json(directory / "call.json")["scenario"]["id"]
                for directory in call_directories(settings.artifacts_dir)
                if not technical_issues(directory)
            }
            selected = [s for s in selected if s["id"] not in completed]
        if not selected:
            print("All selected scenarios already have technical evidence. Review the recordings.")
            return []
        print(
            f"Calling only {TEST_NUMBER} from {settings.caller_id}; "
            f"{len(selected)} call(s), at most {settings.max_call_seconds}s each. "
            "Provider usage is billed. No automatic retries.",
            flush=True,
        )
        results = []
        async with client(settings) as livekit:
            await verify_trunk(settings, livekit)
            async with local_worker(settings) as worker:
                for index, scenario in enumerate(selected, 1):
                    print(f"[{index}/{len(selected)}] {scenario['title']}", flush=True)
                    directory = await execute_call(settings, livekit, scenario, worker)
                    results.append(directory)
                    status = read_json(directory / "status.json")
                    print(f"  {status['status']}: {directory.name}", flush=True)
                    build_index(settings.artifacts_dir)
                    evidence_problems = technical_issues(directory)
                    if status["status"] == "failed" or evidence_problems:
                        raise RuntimeError(
                            "Stopping the batch after a failed call so setup errors do not "
                            "consume the remaining call budget. "
                            f"Inspect {directory / 'status.json'} and the recording."
                        )
                    if index < len(selected):
                        await asyncio.sleep(5)
        build_index(settings.artifacts_dir)
        return results


async def create_trunk(settings: Settings) -> str:
    settings.validate(require_trunk=False)
    address = os.environ.get("SIP_TRUNK_ADDRESS", "").strip()
    username = os.environ.get("SIP_AUTH_USERNAME", "")
    password = os.environ.get("SIP_AUTH_PASSWORD", "")
    if not address.endswith(".pstn.twilio.com") or not username or not password:
        raise ValueError(
            "Set SIP_TRUNK_ADDRESS to your Twilio termination domain, plus "
            "SIP_AUTH_USERNAME and SIP_AUTH_PASSWORD from its Credential List."
        )
    async with client(settings) as livekit:
        result = await livekit.sip.create_sip_outbound_trunk(
            api.CreateSIPOutboundTrunkRequest(
                trunk=api.SIPOutboundTrunkInfo(
                    name="patient-voice-lab-outbound",
                    address=address,
                    numbers=[settings.caller_id],
                    auth_username=username,
                    auth_password=password,
                    transport=api.SIP_TRANSPORT_TCP,
                ),
            )
        )
    return result.sip_trunk_id
