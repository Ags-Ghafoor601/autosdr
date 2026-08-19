# AutoSDR — Recording Guide (start here)

You are recording the two submission videos. This guide assumes you have
**never seen this project before**. Read part 1 twice, do part 2 exactly,
then record parts 3 and 4. Total time needed: about 90 minutes.

Roles: the **driver** operates the laptop (this repo's machine — everything
runs on it); the **narrator** speaks. One person can do both. The WhatsApp
alerts arrive on **Tehseen's phone** (the number connected to Green API), so
have that phone on the desk, unlocked, WhatsApp open on the "Message yourself"
chat.

> Easiest recording method: record the SCREEN doing the actions first (no
> talking), then play it back and record the VOICE over it. You can retry the
> voice as many times as you want without re-doing the demo.

---

## 1 · What is AutoSDR? (read this twice)

**AutoSDR is an autonomous AI sales team in one web app.** You give it two
things: a company's PDF (what the company sells) and a description of the
ideal customer. From there it works alone:

1. **Reads the company PDF** into a knowledge base. Every fact it later uses
   is traceable to a chunk of that PDF (citations).
2. **Searches the live web** for companies matching the ideal customer
   profile, in stages: broad search → a cheap filter kills junk (directories,
   wrong industry) → only survivors get expensive deep research.
3. **Researches each survivor** by scraping their real website and news —
   every claim is stored with a URL + quote as evidence.
4. **Scores each lead 0–100** with a factor-by-factor explanation, and
   **rejects** weak ones (goal: best leads, not most leads).
5. **Picks which service to pitch** each lead, citing the company knowledge.
6. **Finds decision-makers** and their emails (honestly labeled: scraped /
   verified / guessed).
7. **Writes a personalized outreach email** per contact — only from stored
   evidence, so it cannot invent facts — and **sends it through real Gmail**,
   with a booking link inside.
8. **Reads replies** (real IMAP), classifies them (interested / question /
   pricing objection / not interested / …) and answers from company knowledge.
9. **Follows up automatically** if there's no reply after 3 days. On the demo
   clock, 1 day = 60 seconds, so this happens ~3 minutes after outreach —
   visible on camera.
10. **Books meetings**: the prospect picks a slot on a public booking page →
    real video-call link → confirmation email → **WhatsApp alert on the
    admin's phone** → 30 minutes before the meeting, a **WhatsApp briefing**
    (customer problem, what to pitch, likely objections).
11. **Remembers everything** (short-term working state + long-term SQLite
    memory) and shows every step live in the **Agent activity** trace panel.

Extra features to name-drop: human **approval mode** (a toggle that queues
outreach for one-click review before sending), **live public deployment**
(trycloudflare URL), light/dark **themes**, printable **lead reports**,
analytics strip with **cost per qualified lead**.

Safety rule you must say in the video: live emails only go to inboxes the
team owns (allowlist + demo redirect) — the system researches real companies
but never spams them.

Words you'll see: **ICP** = ideal customer profile. **RAG** = the searchable
knowledge base built from the PDF. **Lead** = a company found by the agent.

---

## 2 · Prep (do this ~20 minutes before recording)

Open PowerShell in the repo root (`C:\Users\samra\agenthack-2026\autosdr`).

**Step 1 — fresh database** (wipes old demo data):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\reset_db.ps1
```

**Step 2 — start the server:**

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Leave this window running. Open a SECOND PowerShell window for step 3.

**Step 3 — public tunnel** (also fixes booking links):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\tunnel.ps1
```

**Write down the https://….trycloudflare.com URL it prints.** You'll show it
in both videos. (The tunnel restarts the server — that's normal.)

**Step 4 — set up via the wizard.** Open http://localhost:8000 in Chrome
(clean profile, bookmarks bar hidden, 110% zoom). The wizard appears:

- Step 1: upload `C:\Users\samra\Downloads\AgentHack_company_description.pdf`
  (drag it onto the upload box). Wait ~1 minute for "Company profile built".
- Step 2: fill exactly:
  - Location: `Karachi, Pakistan`
  - Industry: `logistics and courier companies`
  - Size: `SME, 20-500 employees`
  - Targeting: `high volume of WhatsApp and phone inquiries about shipment tracking and dispatch`
- Step 3: Your name: `Tehseen` · leads: `5` · leave approval OFF → **Launch**.

**Step 5 — wait ~10 minutes** while it runs (watch the right-hand Agent
activity feed — searching, filtering, researching, scoring, emailing). While
waiting, practice the narration below out loud twice.

You're ready when: the toolbar says "idle", several companies sit in
Contacted (a couple more in Not qualified / Potential), and ~3 minutes after
outreach you saw follow-up emails fire by themselves in the feed.

**Step 6 — pre-stage these before hitting record:**

- A browser tab with the uni inbox (i243013@isb.nu.edu.pk) — outreach emails
  landed there (they're redirected sandbox copies). Open the newest one and
  **pre-type a reply draft**: `Interesting - what would this cost us monthly? We might want a demo.`
  Do NOT send yet.
- Tehseen's phone: WhatsApp open on the self-chat, screen mirrored with
  scrcpy if available (`winget install Genymobile.scrcpy`, USB debugging on) —
  otherwise film the phone with a second camera when the alerts land, or
  show the Conversation tab's WhatsApp entries instead.
- OBS (or Win+G Game Bar): capture the browser window, 1080p, mic checked.
- Windows Focus Assist ON (no notification popups), WhatsApp Web CLOSED
  (so the phone gets the pings, not the browser).

---

## 3 · Video 1 — Live demo (maximum 1:30)

Record these five beats. If a live beat stalls, keep rolling — you can trim
gaps in any free editor (Clipchamp is preinstalled on Windows 11).

**Beat 1 — 0:00–0:15 · the pipeline board (start here, drawer closed)**
> "This is AutoSDR — an autonomous AI sales team. We gave it one PDF about a
> company called NexaFlow, answered four questions about who to target, and
> pressed Run. Everything on this board happened by itself: it searched the
> web, found these real Karachi logistics companies, and filtered out the junk
> before spending anything on research."

**Beat 2 — 0:15–0:35 · open the highest-scoring Contacted lead (click its card)**
> "Each survivor was deep-researched and scored with reasons — this one
> qualified at [read the number] percent." *(you're on Overview: point at the
> factor bars)* "It picked which NexaFlow service to pitch, citing the
> company knowledge…" *(click the **Research** tab)* "…and every claim is
> backed by evidence scraped from the company's real website — quote plus
> URL. It also rejected companies that didn't fit — best leads, not most
> leads." *(click **Conversation** tab)*

**Beat 3 — 0:35–0:55 · the conversation thread (you're already there)**
> "Then it wrote this personalized email — every fact traces to that
> evidence — and sent it through real Gmail with a booking link inside. No
> reply for three days? On our demo clock that's three minutes — and the
> follow-up sent itself, with a new angle. Watch what happens when the
> prospect replies…"

**Beat 4 — 0:55–1:15 · the live loop.** Switch to the uni-inbox tab, hit
Send on the pre-typed reply. Switch back to AutoSDR, watch the Agent activity
feed (classification appears within ~20 seconds; the drawer updates).
> "The inbox agent picks the reply up over IMAP, classifies it — a pricing
> question — and answers with NexaFlow's real price ranges from the knowledge
> base, nothing invented. Now the prospect books a call…" *(click the booking
> link in the sent email → the public booking page opens → click a slot →
> Confirm)*

**Beat 5 — 1:15–1:30 · the payoff.** Point the camera/mirror at the phone as
the WhatsApp alert arrives (instant), then the briefing (~1 minute later —
if it hasn't arrived when you reach this line, show the previous briefing
message sitting in the same chat).
> "The moment it books: WhatsApp alert on the admin's phone — company, score,
> service, meeting link. And before the call, the agent sends a briefing:
> the customer's problem, what to pitch, likely objections — composed from
> its memory of the whole relationship. One PDF in, meetings out — and it
> works with any company's PDF, not just this one. AutoSDR."

Stop recording. Watch it once; check it's under 1:30.

---

## 4 · Video 2 — Code explanation (maximum 1:00)

Open the repo in VS Code, files pre-opened in this tab order:
`app/agents/` (folder in explorer), `app/rag.py`, `app/agents/discovery.py`,
`app/agents/outreach.py`, `app/scheduler.py`, `README.md` (architecture diagram).

**0:00–0:12 · explorer showing `app/agents/`**
> "AutoSDR is eleven specialized agents around a shared event bus, memory and
> tool layer — FastAPI and SQLite, no agent framework, so every decision is
> explicit and streams to a live trace."

**0:12–0:25 · `rag.py`, then `knowledge.py` prompt**
> "The company PDF becomes a cited knowledge base — chunked, embedded,
> retrieved with chunk-level citations. The knowledge agent even prefers
> current records over outdated ones planted in the document."

**0:25–0:38 · `discovery.py` filter prompt, then `qualify.py` schema**
> "Discovery is staged: search, then a cheap fast-model filter on snippets
> only — the expensive research runs only on survivors. The qualifier outputs
> a confidence score with per-factor reasons, capped by evidence quality, and
> it's allowed to reject."

**0:38–0:50 · `outreach.py` (evidence injection), `inbox.py` (categories)**
> "Outreach is grounded by construction — the composer only ever sees stored
> evidence, quotes with URLs, so it can't invent prospect facts. Replies come
> back over IMAP, get classified, and drive a state machine: follow-ups,
> objection answers, meeting booking."

**0:50–1:00 · `scheduler.py`, then README diagram, then the tunnel URL tab**
> "Time-based autonomy is a scheduler: three-day follow-ups and the
> thirty-minute pre-meeting WhatsApp briefing from long-term memory. It's
> deployed at a public URL, Docker and Render configs in the repo — and one
> rule everywhere: live messages only to inboxes we own."

---

## 5 · If something goes wrong

| Problem | Fix |
|---|---|
| Reply not classified within 30s | Keep rolling; it polls every 20s. Worst case: open the lead's Conversation tab and use "Simulate a prospect reply" — identical flow, badge says sim. |
| Booking page won't open | Use the localhost URL from the email in a new tab; or re-run `scripts\tunnel.ps1` and use the fresh URL. |
| WhatsApp briefing hasn't arrived at the final line | Show the earlier briefing message in the same chat — identical format. |
| Pipeline found few leads | Fine — the demo needs only 2–3 contacted leads. |
| Total disaster mid-take | Stop, breathe, re-record only the broken beat; splice in Clipchamp. |

## 6 · Before you submit

- [ ] Both videos watched start to finish, durations under 1:30 / 1:00
- [ ] Repo pushed (ask Claude/Samran to do a final push if unsure)
- [ ] Submit: Video 1 + Video 2 + https://github.com/samranahmad09/autosdr
- [ ] Screenshot the submission confirmation
