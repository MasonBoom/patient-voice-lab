from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

TEST_NUMBER = "+18054398008"
AGENT_NAME = "patient-voice-lab"
SIP_IDENTITY = "test-receptionist"
E164 = re.compile(r"^\+[1-9]\d{7,14}$")
RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[a-f0-9]{10}$")


def validate_destination(number: str) -> str:
    if number != TEST_NUMBER:
        raise ValueError(f"Only the assessment test line {TEST_NUMBER} may be called.")
    return number


@dataclass(frozen=True)
class Settings:
    url: str
    api_key: str
    api_secret: str
    trunk_id: str
    caller_id: str
    stt_model: str = "deepgram/nova-3"
    llm_model: str = "openai/gpt-5.4-mini"
    tts_model: str = "cartesia/sonic-3"
    tts_voice: str = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
    reasoning_effort: str = "none"
    turn_detection: str = "semantic"
    min_endpoint_delay: float = 0.65
    max_endpoint_delay: float = 3.0
    max_call_seconds: int = 180
    silence_timeout: int = 30
    timezone: str = "America/Los_Angeles"
    profile_path: Path = Path("practice-profile.json")
    artifacts_dir: Path = Path("artifacts")

    @classmethod
    def load(cls) -> Settings:
        load_dotenv(Path.cwd() / ".env", override=False)
        env = os.environ
        return cls(
            url=env.get("LIVEKIT_URL", ""),
            api_key=env.get("LIVEKIT_API_KEY", ""),
            api_secret=env.get("LIVEKIT_API_SECRET", ""),
            trunk_id=env.get("SIP_OUTBOUND_TRUNK_ID", ""),
            caller_id=env.get("CALLER_ID", ""),
            stt_model=env.get("STT_MODEL", "deepgram/nova-3"),
            llm_model=env.get("LLM_MODEL", "openai/gpt-5.4-mini"),
            tts_model=env.get("TTS_MODEL", "cartesia/sonic-3"),
            tts_voice=env.get("TTS_VOICE", "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"),
            reasoning_effort=env.get("LLM_REASONING_EFFORT", "none"),
            turn_detection=env.get("TURN_DETECTION", "semantic"),
            min_endpoint_delay=float(env.get("MIN_ENDPOINT_DELAY", "0.65")),
            max_endpoint_delay=float(env.get("MAX_ENDPOINT_DELAY", "3.0")),
            max_call_seconds=int(env.get("MAX_CALL_SECONDS", "180")),
            silence_timeout=int(env.get("SILENCE_TIMEOUT_SECONDS", "30")),
            timezone=env.get("PRACTICE_TIMEZONE", "America/Los_Angeles"),
            profile_path=Path(env.get("PRACTICE_PROFILE", "practice-profile.json")).resolve(),
            artifacts_dir=Path(env.get("ARTIFACTS_DIR", "artifacts")).resolve(),
        )

    def validate(self, *, require_trunk: bool = True) -> None:
        needed = {
            "LIVEKIT_URL": self.url,
            "LIVEKIT_API_KEY": self.api_key,
            "LIVEKIT_API_SECRET": self.api_secret,
            "CALLER_ID": self.caller_id,
        }
        if require_trunk:
            needed["SIP_OUTBOUND_TRUNK_ID"] = self.trunk_id
        missing = [key for key, value in needed.items() if not value or "your-project" in value]
        if missing:
            raise ValueError("Set these values in .env: " + ", ".join(missing))
        if not self.url.startswith(("wss://", "ws://")):
            raise ValueError("LIVEKIT_URL must start with wss:// (or ws:// for local testing).")
        if not E164.fullmatch(self.caller_id):
            raise ValueError("CALLER_ID must be your owned phone number in E.164 format.")
        if self.caller_id == TEST_NUMBER:
            raise ValueError("CALLER_ID must be your outbound number, not the destination.")
        if not 60 <= self.max_call_seconds <= 240:
            raise ValueError("MAX_CALL_SECONDS must be between 60 and 240.")
        if not 15 <= self.silence_timeout <= 60:
            raise ValueError("SILENCE_TIMEOUT_SECONDS must be between 15 and 60.")
        if not 0.2 <= self.min_endpoint_delay <= self.max_endpoint_delay <= 5.0:
            raise ValueError("Endpoint delays must satisfy 0.2 <= minimum <= maximum <= 5.")
        if self.turn_detection not in {"semantic", "vad"}:
            raise ValueError("TURN_DETECTION must be semantic or vad.")
        if self.reasoning_effort not in {"none", "minimal", "low", "medium", "high"}:
            raise ValueError("Unsupported LLM_REASONING_EFFORT.")
        for model in (self.stt_model, self.llm_model, self.tts_model):
            if any(part in model.lower() for part in ("realtime", "live-audio", "gpt-live")):
                raise ValueError("Speech-to-speech/realtime models are not allowed.")
        ZoneInfo(self.timezone)


def run_directory(root: Path, run_id: str) -> Path:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run ID.")
    return root / run_id
