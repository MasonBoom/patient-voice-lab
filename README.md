# Patient Voice Lab

A Python caller that tests a medical receptionist through real phone conversations,
using LiveKit Agents with **separate STT, text LLM, and TTS stages**. It captures stereo
OGG audio, timestamped transcripts, structured session reports, and reviewable findings.

**Current status:** implementation and offline tests are provided. Real assessment calls,
listening-based iteration, confirmed bugs, repository access, and personal Loom videos
must be completed with configured accounts. No demonstration or synthetic evidence is
presented as a real assessment call.

## Start here on Windows

Use VS Code and PowerShell with Python **3.11 or 3.12** installed.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m livekit.agents download-files
```

Open `.env` and fill in the LiveKit project credentials, outbound trunk ID and your
single owned caller number. Follow [the account setup guide](docs/SETUP.md) to configure
LiveKit and Twilio. Pipeline inference is billed through LiveKit; you do not need three
additional model-provider accounts. Do not commit `.env`.

Create the required assessment test account using the setup URL in the challenge.
Match `practice-profile.json` to that test identity and copy only facts the setup actually
provides. Then set `test_account_created` to `true`. **Do not call the number shown on the
test-account confirmation screen.** The code calls only **+1-805-439-8008** and has no
command-line option or LLM tool to select another destination.

Run the setup check, then one baseline call:

```powershell
.\.venv\Scripts\python.exe -m voice_probe doctor --online
.\.venv\Scripts\python.exe -m voice_probe run --scenario 01-schedule
```

The run command starts the local worker, dispatches a job, makes one call, saves the
evidence, and shuts down. Keep this computer awake and connected. No tunnel, public
webhook, object storage, or external ffmpeg installation is needed.

**Listen to that call before starting the full batch.** Check that the bot stays in the
patient role, responds naturally, preserves dates and times, and lets the receptionist
finish. Record your observations and a real adjustment in [the iteration log](docs/ITERATION_LOG.md).
If needed, edit the prompt, voice, or endpoint delay and rerun the same scenario.

Then collect varied calls:

```powershell
.\.venv\Scripts\python.exe -m voice_probe run --all --resume
.\.venv\Scripts\python.exe -m voice_probe analyze
.\.venv\Scripts\python.exe -m voice_probe report
```

`--resume` skips scenarios with usable technical evidence, including the baseline. It
does not certify conversation quality. Rerun a weak scenario explicitly with `--scenario`.
Calls run sequentially with a short gap, a 180-second default limit, one persistent caller
ID, and no automatic redial. A failed call stops the batch. A call can end sooner if
resolved. Do not pad conversations to hit an arbitrary duration.

## macOS / Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
.venv/bin/python -m livekit.agents download-files
# Fill .env and practice-profile.json before the following commands.
.venv/bin/python -m voice_probe doctor --online
.venv/bin/python -m voice_probe run --scenario 01-schedule
```

After setup, `voice-probe run --all --resume` is the single batch command if the
environment is activated; `python -m voice_probe ...` is equivalent.

For a reproducible install with uv, `uv sync --locked --extra dev` uses the included
`uv.lock`. The pip instructions above are sufficient for ordinary local setup.

## Evidence and review

Each real call creates `artifacts/<UTC timestamp>-<random ID>/` with:

| File | Purpose |
| --- | --- |
| `recording.ogg` | Both sides: left = receptionist; right = simulated patient |
| `transcript.txt` | Readable speaker labels, turn IDs, and offsets into the recording |
| `transcript.json` | Structured turns, interrupted-speech flags, and timing precision |
| `session-report.json` | SDK history, events, model usage, pipeline metrics |
| `call.json` | Scenario, dialed number, caller ID, room and SIP identifiers |
| `status.json` | Technical result and reason the call ended |
| `audio-info.json` | Decoded duration and per-channel signal presence |
| `review.json` | Your honest listening/completeness/transcript review |
| `analysis.json` | Optional evidence-linked candidate findings and human verification |

The patient text comes from the SDK's committed spoken history, including interruption
truncation; the receptionist side comes from STT. Transcription can be wrong. Timing
falls back to a marked estimate when speech timestamps are unavailable. Preserve the
audio and check quotes against it.

After listening, edit each call's `review.json`. Set the four review booleans to `true`
only when accurate and replace `outcome`/`notes` with what actually happened. Calls with
missing audio, a missing side, too few turns, or a timeout need investigation. Signal
checks detect empty channels; they do not prove natural or intelligible conversation.

`analyze` uses a text LLM and never dials. It validates that every proposed finding
cites real turn IDs and an exact receptionist quote. It cannot verify practice policy,
backend changes, or audio quality. Listen, verify facts, then edit each finding's
`status` to `confirmed` or `rejected` and fill in `reviewer_note`. The report preserves
uncertainty and separates receptionist, simulator, and uncertain issues.

Run `report` again to rebuild `artifacts/INDEX.md`, `index.json`, and `BUG_REPORT.md`.
Do not count failed calls or fabricate transcripts, recordings, or bugs.

## Scenarios

`voice-probe scenarios` lists twelve goals: weekday scheduling, rescheduling, cancellation,
refill information, Sunday hours, insurance uncertainty, location, date/time correction,
an ambiguous request, two intents, one deliberate interruption, and name spelling.
These are goals with adaptive follow-up, not scripts read verbatim. Unknown appointments
and office policies are never treated as established facts. Dates are calculated in the
practice timezone, configurable in `.env`.

The interruption scenario schedules one brief correction while the receptionist is
speaking. `interruption.json` records whether that probe actually happened. If the far
end finishes too soon, the harness does not pretend barge-in was tested; listen and rerun.

## Architecture, tests, and submission

- [Architecture and tradeoffs](docs/ARCHITECTURE.md)
- [Accounts, SIP setup, and troubleshooting](docs/SETUP.md)
- [Listening and iteration log](docs/ITERATION_LOG.md)
- [Two video outlines and a genuine debugging workflow](docs/VIDEOS.md)
- [Submission checklist](docs/SUBMISSION.md)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m voice_probe check-submission
```

Tests use local fakes and temporary audio. They make no phone calls and require no API
keys. They check routing restrictions, caller consistency, transcript timing/roles,
real OGG decoding, evidence checks, grounded finding validation, and failure cleanup.
They do not establish telephony/provider performance; those require the live baseline.

Keep the GitHub repository private. Include real recordings and transcripts in it; do
not accidentally ignore `artifacts/`. Use Git LFS if individual recordings exceed GitHub's
file-size limits. Do not use the assessment company's name or initials in the repository
name, description, README title, or videos. Record both videos with your own voice and
webcam. Save receipts for API/phone usage; the challenge describes reimbursement up to
$20, not a guaranteed spending limit. Check provider balances before and after batches.
