from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import Settings
from .evidence import build_index, call_directories, read_json
from .scenarios import get_scenario, load_profile, scenarios


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Patient voice simulator and call evidence tools")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("scenarios", help="List the twelve patient scenarios; no calls")
    doctor = commands.add_parser("doctor", help="Check setup; never places a call")
    doctor.add_argument("--online", action="store_true", help="Also verify the LiveKit SIP trunk")
    run = commands.add_parser("run", help="Start a local worker and make sequential test calls")
    choice = run.add_mutually_exclusive_group(required=True)
    choice.add_argument("--scenario", help="One scenario ID from `scenarios`")
    choice.add_argument("--all", action="store_true", help="Run all twelve scenarios")
    run.add_argument("--resume", action="store_true", help="Skip scenarios with technical evidence")
    commands.add_parser(
        "create-trunk", help="Create a LiveKit outbound trunk; does not place calls"
    )
    analyze = commands.add_parser("analyze", help="Suggest evidence-linked issues using a text LLM")
    analyze.add_argument("--run-id", help="Analyze only this call directory")
    analyze.add_argument("--force", action="store_true", help="Replace existing model analysis")
    commands.add_parser("report", help="Rebuild the call index and findings report offline")
    commands.add_parser("check-submission", help="Check real evidence and submission requirements")
    return result


def doctor(settings: Settings, *, online: bool = False) -> int:
    import importlib.metadata

    errors = []
    try:
        settings.validate()
    except (ValueError, KeyError) as exc:
        errors.append(str(exc))
    try:
        profile = load_profile(settings.profile_path)
        if profile.get("test_account_created") is not True:
            errors.append("Complete the required test account and update practice-profile.json.")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    print(
        f"Python {sys.version.split()[0]}; "
        f"LiveKit Agents {importlib.metadata.version('livekit-agents')}"
    )
    print(f"Pipeline: {settings.stt_model} -> {settings.llm_model} -> {settings.tts_model}")
    print("Audio recording: SDK stereo OGG (no external ffmpeg installation required).")
    if online and not errors:
        from .runner import client, verify_trunk

        async def check():
            async with client(settings) as livekit:
                await verify_trunk(settings, livekit)

        try:
            asyncio.run(check())
            print("LiveKit project and outbound caller ID verified; no phone call placed.")
        except Exception as exc:
            errors.append(f"Online check failed: {type(exc).__name__}: {exc}")
    for error in errors:
        print(f"NEEDS SETUP: {error}")
    return 1 if errors else 0


def check_submission(settings: Settings) -> int:
    index = build_index(settings.artifacts_dir)
    errors = []
    if index["reviewed_complete_calls"] < 10:
        errors.append(
            f"Need at least 10 reviewed complete calls; found {index['reviewed_complete_calls']}."
        )
    if not index["single_caller_id"]:
        errors.append("Call evidence must use exactly one consistent outbound phone number.")
    metadata_path = Path("submission.json")
    submission = read_json(metadata_path) if metadata_path.exists() else {}
    if submission.get("caller_id") not in index["caller_ids"] or not submission.get("caller_id"):
        errors.append("submission.json caller_id must match the actual call evidence.")
    if not str(submission.get("repository_url", "")).startswith("https://github.com/"):
        errors.append("Set your private repository URL in submission.json.")
    for field in (
        "repository_is_private",
        "reviewer_invited",
        "webcam_and_own_voice",
        "receipts_saved",
    ):
        if submission.get(field) is not True:
            errors.append(f"Confirm submission.json: {field}.")
    for field in ("walkthrough_url", "ai_debugging_url"):
        if not str(submission.get(field, "")).startswith(
            ("https://www.loom.com/", "https://loom.com/")
        ):
            errors.append(f"Set a valid, viewable Loom {field} in submission.json.")
    if submission.get("walkthrough_seconds", 999) > 180:
        errors.append("The walkthrough must be at most three minutes.")
    if not submission.get("videos_link_access_checked"):
        errors.append("Verify both videos are viewable by link, using an incognito window.")
    report = settings.artifacts_dir / "BUG_REPORT.md"
    if not report.exists():
        errors.append(
            "Run `voice-probe analyze` and review the findings, or write a factual bug report."
        )
    for error in errors:
        print(f"INCOMPLETE: {error}")
    if not errors:
        print(
            "Local checklist passed. Verify repository access and recordings "
            "before submitting the form."
        )
    print("This local check does not independently verify GitHub permissions or video contents.")
    return 1 if errors else 0


async def run_analysis(settings: Settings, run_id: str | None, force: bool) -> None:
    from .analysis import analyze_call, build_bug_report
    from .config import run_directory

    # Analysis uses LiveKit inference but does not need a telephony trunk or caller ID.
    if not settings.api_key or not settings.api_secret or not settings.url:
        raise ValueError("Set LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET for analysis.")
    directories = (
        [run_directory(settings.artifacts_dir, run_id)]
        if run_id
        else call_directories(settings.artifacts_dir)
    )
    for directory in directories:
        if not (directory / "transcript.json").exists():
            print(f"Skipping {directory.name}: no transcript.")
            continue
        if (directory / "analysis.json").exists() and not force:
            print(f"Keeping {directory.name}: existing analysis (may contain human review).")
            continue
        print(f"Analyzing {directory.name}...", flush=True)
        await analyze_call(directory, settings)
    print(f"Candidate findings report: {build_bug_report(settings.artifacts_dir)}")


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        settings = Settings.load()
        if args.command == "scenarios":
            for scenario in scenarios():
                print(f"{scenario['id']:24} {scenario['title']}")
            return 0
        if args.command == "doctor":
            return doctor(settings, online=args.online)
        if args.command == "run":
            from .runner import run_batch

            selected = scenarios() if args.all else [get_scenario(args.scenario)]
            asyncio.run(run_batch(settings, selected, resume=args.resume))
            print(
                "Listen to the recordings, update each review.json, then run `voice-probe analyze`."
            )
        elif args.command == "create-trunk":
            from .runner import create_trunk

            trunk_id = asyncio.run(create_trunk(settings))
            print(f"Set SIP_OUTBOUND_TRUNK_ID={trunk_id} in .env. No calls were placed.")
        elif args.command == "analyze":
            asyncio.run(run_analysis(settings, args.run_id, args.force))
        elif args.command == "report":
            from .analysis import build_bug_report

            index = build_index(settings.artifacts_dir)
            print(json.dumps({k: v for k, v in index.items() if k != "calls"}, indent=2))
            print(build_bug_report(settings.artifacts_dir))
        elif args.command == "check-submission":
            return check_submission(settings)
        return 0
    except KeyboardInterrupt:
        print("Stopped. Active call cleanup was requested; inspect artifacts before resuming.")
        return 130
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
