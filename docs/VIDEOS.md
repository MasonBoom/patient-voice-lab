# Personal video recordings

Record both with your own spoken voice and webcam. Explain only what you understand
and what the real evidence establishes. The walkthrough must be at most three minutes.
Do not say or show the assessment company's name or initials in the videos. Use neutral
phrasing such as "the receptionist" and "the test line". Hide credentials and account UI.

## Video 1: walkthrough outline (aim for 2:40)

| Time | Show | Explain in your own words |
| --- | --- | --- |
| 0:00-0:20 | Yourself and the project | The patient-simulation goal and why coherent conversations came first |
| 0:20-0:50 | worker.py and architecture | Separate STT / text LLM / TTS; SIP connects the test line to the room |
| 0:50-1:15 | Scenario definition and caller prompt | Goals and adaptive follow-up; no full script readout; consistent identity |
| 1:15-1:50 | One actual recording and its transcript | A short audible excerpt with clear turns; identify who is the caller |
| 1:50-2:15 | Actual iteration log | A real before/after observation, one change and the evidence it helped |
| 2:15-2:40 | Evidence index and one verified issue | Timestamped observation, impact, expected behavior and any uncertainty |

Replace the planned observations with the real results. Do not claim a measured latency
or successful fix unless you measured or heard it. Make the video viewable by link and
test the link in an incognito window.

## Video 2: a real AI-assisted debugging session

Start screen recording **before** reproducing and prompting for a genuine problem. A
live baseline often exposes a useful issue: wrong turn timing, a lost correction, an
audio problem, or SDK/provider behavior. Do not deliberately introduce a defect and
portray it as a naturally discovered issue.

Suggested prompts, adapted to the actual symptom:

1. "This baseline call has [observed symptom] at [timestamp]. Here is the relevant
   transcript, configuration and code. Separate a caller bug from an STT error or
   receptionist behavior. Give the two most likely causes and a focused check for each."
2. "The check showed [actual result]. Propose the smallest fix, explain why it addresses
   that cause, and identify one tradeoff. Do not rewrite unrelated parts of the project."
3. "Review this diff. What could regress in turn-taking, audio capture, or call cleanup?
   Suggest a useful test or same-scenario follow-up call."
4. "Here are the before/after results. Did the change solve the observed problem? What
   is still uncertain? Help me record a factual iteration note."

Show the prompts, the reasoning you accept or reject, the actual edit, and the verification.
If the model is wrong, explain why and adjust. The purpose is to show your judgment, not
to read an AI answer aloud. Use a free Loom account if desired; keep both links accessible.
