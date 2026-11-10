from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from voice_probe.scenarios import build_prompt, get_scenario, load_profile, scenarios


def test_scenarios_are_distinct_and_cover_expected_workflows():
    items = scenarios()
    assert len({item["id"] for item in items}) == 12
    assert sum(bool(item.get("interruption")) for item in items) == 1
    assert all(item["goal"] and len(item["steps"]) >= 3 for item in items)


def test_prompt_has_real_profile_and_future_practice_local_dates(settings):
    scenario = get_scenario("08-date-correction")
    prompt = build_prompt(
        scenario,
        load_profile(settings.profile_path),
        settings,
        now=datetime(2026, 11, 9, 17, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
    )
    assert '"thursday": "2026-11-19"' in prompt
    assert settings.caller_id in prompt
    assert "CALLER, not the" in prompt
    assert "Unknown practice facts must be asked about" in prompt


def test_unknown_scenario_is_an_error():
    with pytest.raises(ValueError, match="Unknown scenario"):
        get_scenario("missing")


def test_module_returns_nonzero_when_service_credentials_missing(tmp_path):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("LIVEKIT_")}
    process = subprocess.run(
        [sys.executable, "-m", "voice_probe", "doctor"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 1
    assert "NEEDS SETUP" in process.stdout
    assert "LIVEKIT_API_SECRET" in process.stdout


def test_submission_check_cannot_pass_with_no_real_calls(tmp_path):
    environment = dict(os.environ, ARTIFACTS_DIR=str(tmp_path / "artifacts"))
    process = subprocess.run(
        [sys.executable, "-m", "voice_probe", "check-submission"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 1
    assert "Need at least 10" in process.stdout


def test_test_account_must_be_completed_before_calling(settings):
    import asyncio

    from voice_probe.runner import run_batch

    profile = load_profile(settings.profile_path)
    profile["test_account_created"] = False
    settings.profile_path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match="Create the assessment test account"):
        asyncio.run(run_batch(settings, [get_scenario("01-schedule")]))
    assert not settings.artifacts_dir.exists()


def test_package_data_is_available():
    assert get_scenario("01-schedule")["opening"]


def test_no_company_name_in_restricted_repo_fields():
    root = Path(__file__).parents[1]
    assert "pretty good ai" not in root.name.lower()
    assert "pgai" not in root.name.lower()
    title = (root / "README.md").read_text().splitlines()[0].lower()
    assert "pretty good ai" not in title and "pgai" not in title
