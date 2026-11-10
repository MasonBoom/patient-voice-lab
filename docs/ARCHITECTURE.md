# Architecture

The local Python runner validates one fixed assessment destination and one persistent
outbound caller ID, starts a LiveKit agent server, and dispatches one scenario per room.
The agent starts listening and recording before creating the SIP participant, so the
receptionist's opening is captured. Twilio Elastic SIP Trunking bridges the phone network
to the room; LiveKit Agents orchestrates **Deepgram Nova-3 STT -> a GPT-5.4 mini text LLM
-> Cartesia Sonic 3 TTS** through LiveKit Inference. These are three independent pipeline
stages, not a speech-to-speech model or hosted voice-agent platform. This keeps model
configuration and billing simple while retaining explicit turn and speech control.
The caller prompt supplies a consistent synthetic identity, practice-local dates, a
patient goal, and adaptive follow-ups. It waits for the receptionist, gives short replies,
asks for clarification, and checks the final outcome. Silero VAD plus LiveKit's local semantic
turn detector provide endpointing; a 650 ms minimum delay and disabled speculative LLM
generation favor complete turns over overly eager replies. Interruptions normally stop
the caller's speech, with false-interruption recovery; only the dedicated barge-in case
deliberately overlaps a single correction. These settings are starting hypotheses to
measure and tune from real recordings, not claims of demonstrated call quality.

LiveKit's session recorder captures the received receptionist audio and the caller's
played audio on separate channels of a shared stereo OGG timeline, preserving silence
and overlaps. On session end, the job copies the finalized recording and writes committed
spoken history, timestamp precision, events, model usage and call identifiers before SDK
cleanup. Using the SDK recorder avoids a second room observer, streaming webhooks, and
an egress/object-store dependency for this small local project. A text-only post-call
reviewer proposes evidence-linked issues, validates cited turns/quotes, and leaves every
finding unconfirmed until a human checks audio and facts. The local checklist requires
ten reviewed complete calls and a single caller number; it never turns failed calls into
successful evidence. Calls have a server-side duration limit, sequential execution,
explicit room deletion on normal/error/cancel paths, and no automatic redial. A direct
Twilio media-stream implementation would require more codec and websocket plumbing;
realtime speech models and hosted voice platforms are excluded by the task. Independent
provider plugins could offer more billing control but add credentials and setup. This
implementation prioritizes one coherent measured baseline before broader scenario
coverage. Real latency, turn recovery, and provider compatibility still need to be
validated with the configured live test line.

References checked when building: [LiveKit Inference](https://docs.livekit.io/agents/models/inference/),
[outbound calling](https://docs.livekit.io/telephony/making-calls/outbound-calls/),
[session data hooks](https://docs.livekit.io/testing/observability/data/), and
[Twilio SIP setup](https://docs.livekit.io/telephony/start/providers/twilio/).
