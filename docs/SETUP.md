# Account and phone setup

## 1. Assessment test account

Use the setup URL in the original challenge: <https://pgai.us/athena>. It currently opens
the Pivot Point Orthopedics intake form. It asks for first name, last name, email, phone
number, and date of birth. Use your eventual owned outbound number here so the identity
matches the assessment calls. The form was inspected; no account has been submitted.
Create the requested test account and review the patient experience. Use a synthetic identity consistently
with `practice-profile.json`; do not include another person's information. If the flow
requires your own verified email, keep it in the test account and local profile as needed.
Copy only observed practice details into the profile; leave unknown details null. Add
any known fact with its source to `verified_facts`, for example an office-hours statement
from that setup flow. The Sunday scenario tests consistency rather than assuming weekends
are closed. Set `test_account_created` to `true` only after completing the setup.

**Never dial the number on its confirmation screen.** The implementation's only outbound
destination is +1-805-439-8008.

## 2. LiveKit Cloud

Create a project at <https://cloud.livekit.io>. Copy its websocket URL, API key, and API
secret into `.env`. Enable/budget LiveKit Inference as needed for your account. This
project uses its Deepgram, OpenAI text LLM, and Cartesia pipeline adapters, which bill
through LiveKit. Agent code runs on your computer; Cloud agent hosting is unnecessary.

Local audio artifacts are collected through the SDK session recorder, and its session
end report is copied before cleanup. Cloud observability can also retain recordings;
it is not a replacement for submitting the local OGG files in your private repository.

## 3. Twilio outbound number and termination trunk

Use <https://console.twilio.com> to create/upgrade a voice-enabled account and obtain
one US voice number you own. A trial account may restrict destinations or SIP usage;
check the account's current limitations before relying on it. Purchasing a number and
provider usage incur charges. Do not rotate the number between test calls.

1. Under Elastic SIP Trunking, create a trunk named `patient-voice-lab`.
2. Configure its **Termination** SIP URI, such as
   `your-unique-trunk.pstn.twilio.com`. Outbound calling uses termination.
3. Create a SIP Credential List with a username and strong password. Associate it with
   this trunk under Termination authentication.
4. Associate your owned number with the trunk. Check US outbound calling permissions.
5. Put that exact number in `.env` as `CALLER_ID=+1...`.

For LiveKit, either create an outbound trunk in its telephony dashboard with that SIP
address, number, username and password, or use this project's helper. The helper needs:

```dotenv
SIP_TRUNK_ADDRESS=your-unique-trunk.pstn.twilio.com
SIP_AUTH_USERNAME=your-sip-username
SIP_AUTH_PASSWORD=your-sip-password
```

These are the SIP Credential List values, not the Twilio account SID/auth token. Then run:

```powershell
.\.venv\Scripts\python.exe -m voice_probe create-trunk
```

Copy the returned ID into `.env` as `SIP_OUTBOUND_TRUNK_ID`. Run the helper once; rerunning
creates another trunk. No inbound dispatch rule or origination URI is required for these
outbound-only calls. The helper does not purchase a number or configure Twilio for you.

Reference: [LiveKit's Twilio guide](https://docs.livekit.io/telephony/start/providers/twilio/)
and [outbound trunks](https://docs.livekit.io/telephony/making-calls/outbound-trunk/).

## 4. Verify before dialing

```powershell
.\.venv\Scripts\python.exe -m livekit.agents download-files
.\.venv\Scripts\python.exe -m voice_probe doctor --online
.\.venv\Scripts\python.exe -m voice_probe run --scenario 01-schedule
```

`doctor` checks configuration without printing secrets. Its online mode verifies that the
outbound trunk exists and includes your caller number, but does not test phone routing
or guarantee model availability. A real baseline establishes those.

## Troubleshooting and iteration

| Symptom | Check / adjustment |
| --- | --- |
| Worker cannot connect | LIVEKIT_URL and project-matched key/secret; inspect artifacts/worker-*.log |
| Detector weights unavailable | Rerun download-files; use TURN_DETECTION=vad temporarily and compare call behavior |
| 401 / 403 on SIP dial | Twilio termination Credential List, caller number association, permissions and account status |
| 404 / invalid trunk | Use the LiveKit outbound trunk ID, not Twilio's trunk SID |
| Destination disallowed on trial | Review provider restrictions; do not change the assessment destination to test another number |
| Missing first greeting | Check that session/recording starts before SIP dialing; compare the raw audio and transcript |
| Talks too early | Raise MIN_ENDPOINT_DELAY modestly (e.g. 0.8), listen again; change one setting at a time |
| Slow responses | Review session-report message metrics, network, model TTFT and TTS TTFB; keep responses brief |
| Stops on backchannels | Compare interruption thresholds and detector mode using the same scenario |
| Appointment not found | Ensure profile matches the test identity; accept no-match behavior without inventing records |
| Empty / one-sided audio | Inspect status.json and audio-info.json; repair before counting or running more calls |
| Unexpected disconnect | Inspect SIP call ID and provider call logs; do not hide the failure or count it as complete |
| Stale .run-lock | Confirm the previous runner/worker is stopped before removing the lock |

Keep logs and short before/after observations. Do not put credentials, account pages, or
payment information in either Loom recording.
