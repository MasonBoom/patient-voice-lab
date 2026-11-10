from __future__ import annotations

import json
from pathlib import Path

import av
import numpy as np
import pytest

from voice_probe.config import Settings


@pytest.fixture
def settings(tmp_path):
    profile = {
        "test_patient": {
            "first_name": "Alex",
            "last_name": "Morgan",
            "date_of_birth": "1988-04-12",
        },
        "practice": {},
        "verified_facts": [],
        "test_account_created": True,
    }
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile), "utf-8")
    return Settings(
        url="wss://example.livekit.cloud",
        api_key="test-key",
        api_secret="test-secret",
        trunk_id="ST_test",
        caller_id="+15555550123",
        turn_detection="vad",
        profile_path=profile_path,
        artifacts_dir=tmp_path / "artifacts",
    )


def make_ogg(path: Path, *, silent_right: bool = False, seconds: float = 1.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 48000
    samples = int(rate * seconds)
    phase = np.arange(samples) / rate
    left = (0.2 * np.sin(2 * np.pi * 440 * phase)).astype(np.float32)
    right = (
        np.zeros(samples, np.float32)
        if silent_right
        else (0.2 * np.sin(2 * np.pi * 660 * phase)).astype(np.float32)
    )
    with av.open(str(path), "w", format="ogg") as output:
        stream = output.add_stream("libopus", rate=rate)
        stream.layout = "stereo"
        frame = av.AudioFrame.from_ndarray(np.stack([left, right]), format="fltp", layout="stereo")
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    return path
