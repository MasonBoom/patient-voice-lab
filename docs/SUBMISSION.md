# Submission checklist

The project code alone is not a complete submission. Check the original challenge
again before sending anything.

- [ ] Required test account created; profile matches it.
- [ ] Only +1-805-439-8008 called, always from the same owned E.164 caller number.
- [ ] At least 10 full real conversations; listen to every counted recording.
- [ ] Both sides audible in OGG files and present in transcripts.
- [ ] Real iteration after listening to early results, recorded in the iteration log.
- [ ] Bug report contains useful, verified findings with call/turn/timestamp evidence.
- [ ] Candidate issues and caller failures distinguished from confirmed receptionist bugs.
- [ ] README, 1-2 paragraph architecture document, Python code and .env.example included.
- [ ] No API keys, SIP passwords, or .env files in Git history.
- [ ] Private GitHub repository with a neutral name, description and README title.
- [ ] Invite the exact collaborator address specified in the challenge through GitHub
      Settings -> Collaborators -> Add people; do not send an assessment-support email.
- [ ] All real audio and transcript files committed; verify they open from the private repo.
- [ ] Walkthrough Loom (at most 3 minutes) with your voice and webcam.
- [ ] Separate Loom showing you actually prompting AI to debug and fix a real issue,
      with your voice and webcam.
- [ ] No assessment-company name or initials used or visible in either video.
- [ ] Both Loom links viewable by link; test in an incognito window.
- [ ] Exact caller ID copied from actual call metadata into the submission form.
- [ ] Provider receipts saved for the stated reimbursement process (up to $20).
- [ ] Populate submission.json and run `voice-probe check-submission`.
- [ ] Submit through the challenge's submission form and keep the repository private.

The supplied PDF's submission-form text is not necessarily a clickable URL. Use the
actual link from the assessment invitation. Do not guess or submit to an unrelated form.
The local checklist cannot independently verify repository permissions, video contents,
backend behavior, or a form submission.

To create the private repository yourself after checking the evidence:

```powershell
git init
git add .
git status
git commit -m "Build patient voice simulator and evidence workflow"
gh repo create patient-voice-lab --private --source . --remote origin --push
```

Review staged files before committing. `gh` requires GitHub CLI authentication. The
recordings are intentionally not ignored. Do not publish this repository or change it
to public visibility after submission.
