from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from voice_probe.config import TEST_NUMBER, run_directory, validate_destination
from voice_probe.evidence import write_json
from voice_probe.runner import batch_lock, enforce_single_caller, execute_call, verify_trunk
from voice_probe.scenarios import get_scenario


@pytest.mark.parametrize("number", ["+18054398009", "+15555550123", "18054398008", "", None])
def test_rejects_every_non_assessment_destination(number):
    with pytest.raises(ValueError, match="Only the assessment"):
        validate_destination(number)


def test_assessment_destination_allowed():
    assert validate_destination(TEST_NUMBER) == "+18054398008"


@pytest.mark.parametrize("run_id", ["../outside", "/tmp/file", "x", "20261109T120000Z-../../x"])
def test_run_metadata_cannot_escape_artifact_root(tmp_path, run_id):
    with pytest.raises(ValueError, match="Invalid run"):
        run_directory(tmp_path, run_id)


def test_caller_cannot_change_between_batches(tmp_path):
    enforce_single_caller(tmp_path, "+15555550123")
    enforce_single_caller(tmp_path, "+15555550123")
    with pytest.raises(ValueError, match="already locked"):
        enforce_single_caller(tmp_path, "+15555550124")


def test_existing_evidence_cannot_be_mixed_with_another_caller(tmp_path):
    write_json(tmp_path / "call-1" / "call.json", {"caller_id": "+15555550123"})
    with pytest.raises(ValueError, match="another caller"):
        enforce_single_caller(tmp_path, "+15555550124")


def test_concurrent_batches_rejected_and_lock_released_on_error(tmp_path):
    with pytest.raises(RuntimeError):
        with batch_lock(tmp_path):
            with pytest.raises(ValueError, match="Another batch"):
                with batch_lock(tmp_path):
                    pass
            raise RuntimeError("simulate canceled batch")
    assert not (tmp_path / ".run-lock").exists()


def test_refuses_trunk_with_another_caller_id(settings):
    trunk = SimpleNamespace(sip_trunk_id=settings.trunk_id, numbers=["+15555550124"])
    livekit = SimpleNamespace(
        sip=SimpleNamespace(
            list_sip_outbound_trunk=AsyncMock(return_value=SimpleNamespace(items=[trunk])),
        )
    )
    with pytest.raises(ValueError, match="not one of"):
        asyncio.run(verify_trunk(settings, livekit))


def test_failed_dispatch_still_deletes_the_phone_room(settings):
    livekit = SimpleNamespace(
        room=SimpleNamespace(create_room=AsyncMock(), delete_room=AsyncMock()),
        agent_dispatch=SimpleNamespace(
            create_dispatch=AsyncMock(side_effect=RuntimeError("offline"))
        ),
    )
    with pytest.raises(RuntimeError, match="offline"):
        asyncio.run(execute_call(settings, livekit, get_scenario("01-schedule"), None))
    livekit.room.delete_room.assert_awaited_once()
    statuses = list(settings.artifacts_dir.glob("*/status.json"))
    assert len(statuses) == 1
    assert '"failed"' in statuses[0].read_text()


@pytest.mark.parametrize("model", ["openai/gpt-realtime", "google/gemini-live-audio"])
def test_realtime_models_refused(settings, model):
    with pytest.raises(ValueError, match="not allowed"):
        replace(settings, llm_model=model).validate()


def test_valid_settings_pass(settings):
    settings.validate()
