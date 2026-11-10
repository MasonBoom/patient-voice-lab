from __future__ import annotations

from types import SimpleNamespace

import av
import pytest
from conftest import make_ogg
from livekit.agents import llm

from voice_probe.config import TEST_NUMBER
from voice_probe.evidence import (
    build_index,
    inspect_audio,
    persist_session,
    read_json,
    technical_issues,
    transcript_from_history,
    write_json,
)


def history():
    return SimpleNamespace(
        items=[
            llm.ChatMessage(role="system", content=["Do not export this prompt"]),
            llm.ChatMessage(
                role="user",
                content=["How can I help?"],
                created_at=103,
                metrics={"started_speaking_at": 101.25},
            ),
            llm.ChatMessage(
                role="assistant",
                content=["I'd like Thursday"],
                created_at=105,
                interrupted=True,
            ),
            llm.ChatMessage(role="user", content=["Which time?"], created_at=107),
            llm.ChatMessage(role="assistant", content=["After 2 pm, please."], created_at=108),
        ]
    )


def test_transcript_maps_system_under_test_and_records_timing_precision():
    turns = transcript_from_history(history(), 100)
    assert [turn["speaker"] for turn in turns] == [
        "receptionist",
        "patient",
        "receptionist",
        "patient",
    ]
    assert turns[0]["start_seconds"] == 1.25
    assert turns[0]["timing_source"] == "speech_metrics"
    assert turns[1]["start_seconds"] == 5
    assert turns[1]["timing_source"] == "message_created_estimate"
    assert turns[1]["interrupted"] is True
    assert all("Do not export" not in turn["text"] for turn in turns)


def test_both_audio_channels_are_decoded_and_checked(tmp_path):
    path = make_ogg(tmp_path / "recording.ogg")
    info = inspect_audio(path)
    assert info["codec"] == "opus"
    assert info["channels"] == 2
    assert 0.95 <= info["duration_seconds"] <= 1.05
    assert all(seconds > 0.5 for seconds in info["active_seconds"])


def test_silent_patient_channel_not_mistaken_for_a_conversation(tmp_path):
    path = make_ogg(tmp_path / "recording.ogg", silent_right=True)
    info = inspect_audio(path)
    assert info["active_seconds"][0] > 0.5
    assert info["active_seconds"][1] == 0


def test_text_file_is_not_accepted_as_audio(tmp_path):
    path = tmp_path / "recording.ogg"
    path.write_text("fake audio " * 100)
    with pytest.raises((av.FFmpegError, ValueError)):
        inspect_audio(path)


def setup_evidence(directory, tmp_path, *, silent_right=False):
    audio = make_ogg(tmp_path / "sdk" / "audio.ogg", silent_right=silent_right)
    report = SimpleNamespace(
        audio_recording_started_at=100,
        audio_recording_path=audio,
        chat_history=history(),
        to_dict=lambda: {"sdk_version": "test", "audio_recording_path": str(audio)},
    )
    directory.mkdir(parents=True, exist_ok=True)
    persist_session(directory, report)
    write_json(
        directory / "call.json",
        {
            "scenario": {"id": "01-schedule", "title": "Schedule"},
            "caller_id": "+15555550123",
            "destination": TEST_NUMBER,
            "answered_at": 100,
        },
    )
    write_json(directory / "status.json", {"status": "complete", "end_reason": "goal_resolved"})
    return directory


def test_evidence_is_copied_before_sdk_temporary_file_disappears(tmp_path):
    directory = setup_evidence(tmp_path / "artifacts" / "run-1", tmp_path)
    (tmp_path / "sdk" / "audio.ogg").unlink()
    assert inspect_audio(directory / "recording.ogg")["channels"] == 2
    assert read_json(directory / "review.json")["full_conversation"] is False
    assert "[~00:05] turn-002 PATIENT [interrupted]" in (directory / "transcript.txt").read_text()


def test_call_not_counted_without_listening_review(tmp_path):
    root = tmp_path / "artifacts"
    directory = setup_evidence(root / "run-1", tmp_path)
    assert technical_issues(directory) == []
    assert build_index(root)["reviewed_complete_calls"] == 0
    write_json(
        directory / "review.json",
        {
            "listened_to_audio": True,
            "both_sides_clear": True,
            "full_conversation": True,
            "transcript_checked": True,
        },
    )
    assert build_index(root)["reviewed_complete_calls"] == 1


def test_timeout_call_not_counted_despite_manual_flags(tmp_path):
    root = tmp_path / "artifacts"
    directory = setup_evidence(root / "run-1", tmp_path)
    write_json(directory / "status.json", {"status": "complete", "end_reason": "silence_timeout"})
    assert any("silence_timeout" in issue for issue in technical_issues(directory))
    assert build_index(root)["reviewed_complete_calls"] == 0


def test_corrupt_recording_stays_visible_in_index(tmp_path):
    root = tmp_path / "artifacts"
    directory = setup_evidence(root / "run-1", tmp_path)
    (directory / "recording.ogg").write_text("corrupt audio" * 100)
    index = build_index(root)
    assert index["total_attempts"] == 1
    assert index["reviewed_complete_calls"] == 0
    assert index["calls"][0]["technical_issues"]


def test_evidence_for_another_destination_cannot_be_counted(tmp_path):
    directory = setup_evidence(tmp_path / "artifacts" / "run-1", tmp_path)
    call = read_json(directory / "call.json")
    call["destination"] = "+15555550999"
    write_json(directory / "call.json", call)
    assert any("authorized assessment" in issue for issue in technical_issues(directory))
