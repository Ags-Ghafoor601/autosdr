# AgentHack 2026 — Submission Checklist

**Deadline: Sunday 16 Aug, 3:00 PM PKT. Target: submitted by noon.**

## The three mandatory artifacts

| # | Artifact | Limit | Status |
|---|---|---|---|
| 1 | Live Demo Video | ≤ 1:30 | ☐ record tonight (script: RECORDING_GUIDE.md) |
| 2 | Code Explanation Video | ≤ 1:00 | ☐ record tonight (script: RECORDING_GUIDE.md) |
| 3 | GitHub repository link | must contain `.env.example` | ✅ https://github.com/samranahmad09/autosdr — per organizer: **private + organizer as collaborator + committed `.env`** (OpenAI/Serper only; personal creds stay in gitignored `.env.local`) |

## Before hitting record

- [ ] `scripts\reset_db.ps1` → restart server → fresh pipeline run (~10 min)
- [ ] Confirm on the fresh run: outreach LIVE to sandbox inbox, follow-up fires ~3 min later, booking → WhatsApp alert → briefing reminder
- [ ] Phone mirrored (scrcpy), WhatsApp self-chat visible, uni inbox open with pre-typed reply draft

## Before submitting

- [ ] Watch both videos start-to-finish once (audio, duration under limits)
- [ ] Repo: final `git push`; check README + mermaid diagram render on github.com
- [ ] Confirm in the WhatsApp group WHERE videos go (Drive/YouTube-unlisted/direct upload) and submit all three together
- [ ] Repo private + organizer added as collaborator + judge `.env` pushed (see chat steps)
- [ ] Screenshot the submission confirmation

## After results are announced

- [ ] **Rotate the OpenAI API key** (it is in git history) — platform.openai.com → API keys
- [ ] Rotate the Serper key if the repo ever goes public again
- [ ] Remove the organizer collaborator when judging ends

## One-paragraph project summary (paste wherever a description is asked)

> AutoSDR is an autonomous AI sales team built for the AgentHack Autonomous AI
> Sales Agent challenge. It ingests a company PDF into a cited RAG knowledge
> layer, converts targeting answers into a structured ICP, then runs the full
> sales lifecycle autonomously: staged lead discovery (search → cheap filter →
> deep research), evidence-based qualification with explained confidence scores
> (including honest rejections), RAG-grounded service matching, decision-maker
> identification, role-personalized evidence-cited outreach with per-email
> booking links, IMAP reply classification driving a next-action state machine,
> scheduled 3-day follow-ups, meeting booking with real video-call links, and
> WhatsApp admin alerts including a 30-minute pre-meeting briefing composed from
> long-term memory. Eleven specialized agents share an event bus whose every
> plan, tool call and decision streams to a live trace panel — with short-term
> and long-term memory maintained across the entire customer lifecycle.
