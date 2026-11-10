from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path

import av
import numpy as np

from .config import TEST_NUMBER


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", "utf-8")
    os.replace(temporary, path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def transcript_from_history(history, recording_started_at: float) -> list[dict]:
    turns = []
    for item in history.items:
        if item.type != "message" or item.role not in {"user", "assistant"}:
            continue
        text = item.text_content
        if not text or not text.strip():
            continue
        metrics = item.metrics or {}
        began = metrics.get("started_speaking_at")
        # Some messages (including interrupted speech) have no speech timing yet.
        # Preserve the fallback and label its reduced precision explicitly.
        start = began if began is not None else item.created_at
        turns.append(
            {
                "id": f"turn-{len(turns) + 1:03d}",
                "speaker": "receptionist" if item.role == "user" else "patient",
                "text": text.strip(),
                "start_seconds": round(max(0, start - recording_started_at), 3),
                "timing_source": "speech_metrics"
                if began is not None
                else "message_created_estimate",
                "interrupted": item.interrupted,
                "message_id": item.id,
            }
        )
    return turns


def inspect_audio(path: Path) -> dict:
    """Decode the real file; a nonempty placeholder is not sufficient evidence."""
    if not path.is_file() or path.stat().st_size < 100:
        raise ValueError("Recording is missing or empty.")
    energy: np.ndarray | None = None
    samples = 0
    active_samples: np.ndarray | None = None
    rate = 0
    with av.open(str(path)) as container:
        if "ogg" not in container.format.name and "mp3" not in container.format.name:
            raise ValueError("Recording must be OGG or MP3.")
        stream = container.streams.audio[0]
        channels = len(stream.layout.channels)
        codec = stream.codec_context.name
        for frame in container.decode(stream):
            audio = frame.to_ndarray()
            # Decoder output is planar for Opus and may be packed for MP3.
            if not frame.format.is_planar:
                audio = audio.reshape(-1, channels).T
            audio = audio.astype(np.float64)
            if not frame.format.name.startswith(("flt", "dbl")):
                audio /= float(2 ** (frame.format.bytes * 8 - 1))
            if energy is None:
                energy = np.zeros(channels)
                active_samples = np.zeros(channels, dtype=np.int64)
            energy += np.square(audio).sum(axis=1)
            # A basic presence check, not a speech/intelligibility score.
            active_samples += (np.abs(audio) > 0.01).sum(axis=1)
            samples += audio.shape[1]
            rate = frame.sample_rate
    if samples == 0 or energy is None or active_samples is None:
        raise ValueError("Recording contains no decodable audio samples.")
    return {
        "codec": codec,
        "channels": channels,
        "sample_rate": rate,
        "duration_seconds": round(samples / rate, 3),
        "rms_dbfs": [round(10 * math.log10(max(e / samples, 1e-12)), 2) for e in energy],
        "active_seconds": [round(int(count) / rate, 3) for count in active_samples],
        "channel_map": {"0": "receptionist", "1": "patient"},
        "note": "Signal presence does not establish intelligibility; listen to both channels.",
    }


def persist_session(directory: Path, report) -> dict:
    """Called after the SDK closes its recorder, before it removes the job directory."""
    write_json(directory / "session-report.json", report.to_dict())
    if report.audio_recording_started_at is None:
        raise ValueError("The session did not expose a recording start time.")
    turns = transcript_from_history(report.chat_history, report.audio_recording_started_at)
    transcript = {
        "source": "LiveKit committed session history",
        "recording_epoch": report.audio_recording_started_at,
        "note": "ASR and spoken-text alignment may contain errors. Verify quotes against audio.",
        "turns": turns,
    }
    write_json(directory / "transcript.json", transcript)
    lines = [
        "PATIENT SIMULATOR CALL TRANSCRIPT",
        "Time offsets refer to recording.ogg; estimated offsets are marked ~.",
        "receptionist = system under test; patient = our simulator.",
        "ASR is not ground truth. Check the recording before confirming a finding.",
        "",
    ]
    for turn in turns:
        estimated = "~" if turn["timing_source"] != "speech_metrics" else ""
        cut = " [interrupted]" if turn["interrupted"] else ""
        lines.append(
            f"[{estimated}{timestamp(turn['start_seconds'])}] {turn['id']} "
            f"{turn['speaker'].upper()}{cut}: {turn['text']}"
        )
    (directory / "transcript.txt").write_text("\n".join(lines) + "\n", "utf-8")
    source = report.audio_recording_path
    if source is None or not Path(source).is_file():
        raise ValueError("The SDK did not produce an audio recording.")
    destination = directory / "recording.ogg"
    shutil.copy2(source, destination)
    audio = inspect_audio(destination)
    write_json(directory / "audio-info.json", audio)
    if not (directory / "review.json").exists():
        write_json(
            directory / "review.json",
            {
                "listened_to_audio": False,
                "both_sides_clear": False,
                "full_conversation": False,
                "transcript_checked": False,
                "outcome": "pending",
                "notes": "Listen to this real call, then set these review fields honestly.",
            },
        )
    return audio


def technical_issues(directory: Path) -> list[str]:
    issues: list[str] = []
    try:
        status = read_json(directory / "status.json")
        metadata = read_json(directory / "call.json")
        transcript = read_json(directory / "transcript.json")
        audio = inspect_audio(directory / "recording.ogg")
    except (OSError, ValueError, IndexError, av.FFmpegError) as exc:
        return [f"Missing or invalid evidence: {type(exc).__name__}: {exc}"]
    if status.get("status") != "complete" or not metadata.get("answered_at"):
        issues.append("Call did not finish with an answered SIP connection.")
    if metadata.get("destination") != TEST_NUMBER:
        issues.append("Call metadata does not identify the authorized assessment test line.")
    if audio["channels"] != 2 or any(value < 0.25 for value in audio["active_seconds"]):
        issues.append("Two audible speaker channels were not established.")
    for speaker in ("patient", "receptionist"):
        count = sum(turn["speaker"] == speaker for turn in transcript["turns"])
        if count < 2:
            issues.append(
                f"Only {count} committed {speaker} turns; inspect conversation completeness."
            )
    if status.get("end_reason") in {"error", "no_greeting", "silence_timeout", "max_duration"}:
        issues.append(f"Call ended because of {status['end_reason']}; rerun or investigate.")
    return issues


def review_issues(directory: Path) -> list[str]:
    try:
        review = read_json(directory / "review.json")
    except (OSError, ValueError):
        return ["Call has not been reviewed."]
    fields = ("listened_to_audio", "both_sides_clear", "full_conversation", "transcript_checked")
    return [f"Review not confirmed: {field}" for field in fields if review.get(field) is not True]


def call_directories(root: Path) -> list[Path]:
    return sorted(path.parent for path in root.glob("*/call.json"))


def build_index(root: Path) -> dict:
    rows = []
    numbers = set()
    for directory in call_directories(root):
        call = read_json(directory / "call.json")
        numbers.add(call.get("caller_id"))
        technical = technical_issues(directory)
        review = review_issues(directory)
        status = (
            read_json(directory / "status.json") if (directory / "status.json").exists() else {}
        )
        rows.append(
            {
                "run_id": directory.name,
                "scenario_id": call["scenario"]["id"],
                "title": call["scenario"]["title"],
                "status": status.get("status", "unknown"),
                "end_reason": status.get("end_reason"),
                "technical_issues": technical,
                "review_issues": review,
                "eligible": not technical and not review,
            }
        )
    result = {
        "calls": rows,
        "total_attempts": len(rows),
        "reviewed_complete_calls": sum(row["eligible"] for row in rows),
        "caller_ids": sorted(number for number in numbers if number),
        "single_caller_id": len(numbers) == 1 and None not in numbers,
    }
    write_json(root / "index.json", result)
    lines = [
        "# Call evidence",
        "",
        f"Attempts: {len(rows)}. Reviewed complete calls: {result['reviewed_complete_calls']}.",
        "",
        "| Call | Scenario | Status | Review | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        run_id = row["run_id"]
        review = "complete" if row["eligible"] else "needs review / repair"
        links = f"[audio]({run_id}/recording.ogg) / [transcript]({run_id}/transcript.txt)"
        lines.append(f"| {run_id} | {row['scenario_id']} | {row['status']} | {review} | {links} |")
    (root / "INDEX.md").write_text("\n".join(lines) + "\n", "utf-8")
    return result
