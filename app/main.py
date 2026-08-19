"""AutoSDR — autonomous AI sales agent. FastAPI app + SSE trace stream."""
import asyncio
import json

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import bus, db, memory
from .config import ROOT, UPLOAD_DIR, EMAIL_MODE, WHATSAPP_MODE, SECONDS_PER_DAY

app = FastAPI(title="AutoSDR")


@app.on_event("startup")
async def startup():
    db.conn()
    bus.bind_loop(asyncio.get_running_loop())
    bus.emit("system", "step", "AutoSDR started",
             {"email_mode": EMAIL_MODE, "whatsapp_mode": WHATSAPP_MODE,
              "seconds_per_day": SECONDS_PER_DAY})
    from . import scheduler
    scheduler.start()
    from . import llm
    if llm.RESOLVED["reason"] and llm.RESOLVED["fast"]:
        bus.emit("llm", "step", f"models (env): {llm.RESOLVED['reason']} / {llm.RESOLVED['fast']}")
    else:
        def _resolve():
            try:
                llm.resolve_models()
            except Exception as e:  # noqa: BLE001
                bus.emit("llm", "error", f"model resolution failed: {str(e)[:140]} "
                                         f"(is OPENAI_API_KEY set in .env?)")
        await asyncio.to_thread(_resolve)


# ── setup: company knowledge + ICP ───────────────────────────────────────

@app.post("/api/company/upload")
async def company_upload(file: UploadFile = File(...)):
    from .agents import knowledge
    dest = UPLOAD_DIR / file.filename
    dest.write_bytes(await file.read())
    try:
        profile = await asyncio.to_thread(knowledge.build_profile, file.filename, None, str(dest))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "profile": profile}


@app.post("/api/company/text")
async def company_text(name: str = Form("company description"), text: str = Form(...)):
    from .agents import knowledge
    if not text.strip():
        raise HTTPException(400, "empty text")
    profile = await asyncio.to_thread(knowledge.build_profile, name, text, None)
    return {"ok": True, "profile": profile}


@app.post("/api/icp")
async def set_icp(location: str = Form(""), industry: str = Form(""),
                  size: str = Form(""), targeting: str = Form("")):
    from .agents import icp as icp_agent
    if not db.kv_get("company_profile"):
        raise HTTPException(400, "ingest the company document first")
    icp = await asyncio.to_thread(icp_agent.build_icp,
                                  {"location": location, "industry": industry,
                                   "size": size, "targeting": targeting})
    return {"ok": True, "icp": icp}


@app.get("/api/memory")
async def memory_view():
    return {
        "short_term": memory.snapshot(),
        "long_term_notes": db.rows("SELECT * FROM memory_notes ORDER BY ts DESC LIMIT 50"),
    }


@app.get("/api/stats")
async def stats():
    counts = {r["stage"]: r["n"] for r in
              db.rows("SELECT stage, COUNT(*) n FROM leads GROUP BY stage")}
    total = sum(counts.values())
    qualified_plus = sum(counts.get(s, 0) for s in
                         ("qualified", "contacted", "interested", "meeting_scheduled", "converted"))
    emails_out = db.one("SELECT COUNT(*) n FROM messages WHERE direction='out' "
                        "AND channel LIKE 'email%' AND status!='draft'")["n"]
    live_out = db.one("SELECT COUNT(*) n FROM messages WHERE direction='out' AND channel='email'")["n"]
    replies = db.one("SELECT COUNT(*) n FROM messages WHERE direction='in'")["n"]
    wa = db.one("SELECT COUNT(*) n FROM messages WHERE channel LIKE 'whatsapp%'")["n"]
    meetings = db.one("SELECT COUNT(*) n FROM meetings")["n"]
    avg_q = db.one("SELECT AVG(score) a FROM leads WHERE score IS NOT NULL AND stage IN "
                   "('qualified','contacted','interested','meeting_scheduled','converted')")["a"]
    costs = db.kv_get("costs", {"usd": 0.0, "calls": 0})
    return {
        "funnel": counts, "total_leads": total, "qualified_plus": qualified_plus,
        "emails_out": emails_out, "emails_live": live_out, "replies": replies,
        "whatsapp": wa, "meetings": meetings,
        "avg_qualified_score": round(avg_q, 1) if avg_q else None,
        "cost_usd": costs.get("usd", 0.0), "llm_calls": costs.get("calls", 0),
        "cost_per_qualified": round(costs.get("usd", 0.0) / qualified_plus, 4) if qualified_plus else None,
        "approval_mode": bool(db.kv_get("approval_mode", False)),
        "pending_approvals": db.one("SELECT COUNT(*) n FROM messages WHERE status='draft'")["n"],
    }


# ── human-in-the-loop approval mode ──────────────────────────────────────

@app.post("/api/settings/approval")
async def set_approval(enabled: bool = Form(...)):
    db.kv_set("approval_mode", bool(enabled))
    bus.emit("system", "step",
             f"approval mode {'ON — outreach queues for human review' if enabled else 'OFF — fully autonomous sends'}")
    return {"ok": True, "approval_mode": bool(enabled)}


@app.get("/api/outbox")
async def outbox():
    drafts = db.rows("SELECT m.*, l.name lead_name FROM messages m "
                     "LEFT JOIN leads l ON l.id=m.lead_id "
                     "WHERE m.status='draft' ORDER BY m.ts")
    for d in drafts:
        if d.get("meta"):
            d["meta"] = json.loads(d["meta"])
    return {"drafts": drafts}


@app.post("/api/outbox/{message_id}/approve")
async def approve_draft(message_id: str):
    from .tools import emailer
    d = db.one("SELECT * FROM messages WHERE id=? AND status='draft'", (message_id,))
    if not d:
        raise HTTPException(404, "draft not found or already handled")
    meta = json.loads(d["meta"] or "{}")
    to_addr = meta.get("to_addr", "")
    db.update("messages", message_id, {"status": "approved"})
    bus.emit("outreach", "decision", f"human approved draft → sending to {to_addr}",
             lead_id=d["lead_id"])
    res = await asyncio.to_thread(
        emailer.send, to_addr, d["subject"], d["body"],
        lead_id=d["lead_id"], contact_id=d["contact_id"],
        meta={**meta, "approved_from_draft": message_id})
    return {"ok": True, **res}


@app.post("/api/outbox/{message_id}/reject")
async def reject_draft(message_id: str):
    d = db.one("SELECT * FROM messages WHERE id=? AND status='draft'", (message_id,))
    if not d:
        raise HTTPException(404, "draft not found or already handled")
    db.update("messages", message_id, {"status": "rejected"})
    bus.emit("outreach", "step", "human rejected draft — not sent", lead_id=d["lead_id"])
    return {"ok": True}


# ── pipeline control ─────────────────────────────────────────────────────

@app.post("/api/run")
async def run_pipeline(max_leads: int = Form(5), threshold: int = Form(60),
                       sender_name: str = Form("Tehseen")):
    from . import orchestrator
    if orchestrator.running():
        raise HTTPException(409, "pipeline already running")
    orchestrator.start_run_async(max_leads, threshold, sender_name)
    return {"ok": True, "started": True}


@app.post("/api/stop")
async def stop_pipeline():
    from . import orchestrator
    orchestrator.stop()
    return {"ok": True}


@app.post("/api/leads/{lead_id}/advance")
async def advance_lead(lead_id: str):
    from . import orchestrator
    await asyncio.to_thread(orchestrator.advance_one, lead_id)
    return {"ok": True}


@app.get("/api/leads/{lead_id}")
async def lead_detail(lead_id: str):
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead:
        raise HTTPException(404, "no such lead")
    for f in ("score_reasons", "service", "research"):
        if lead.get(f):
            lead[f] = json.loads(lead[f])
    msgs = db.rows("SELECT * FROM messages WHERE lead_id=? ORDER BY ts", (lead_id,))
    for m in msgs:
        if m.get("meta"):
            m["meta"] = json.loads(m["meta"])
    return {
        "lead": lead,
        "contacts": db.rows("SELECT * FROM contacts WHERE lead_id=?", (lead_id,)),
        "evidence": db.rows("SELECT * FROM evidence WHERE lead_id=? ORDER BY ts", (lead_id,)),
        "messages": msgs,
        "meetings": db.rows("SELECT * FROM meetings WHERE lead_id=?", (lead_id,)),
        "followups": db.rows("SELECT * FROM followups WHERE lead_id=? ORDER BY due_ts", (lead_id,)),
        "notes": db.rows("SELECT * FROM memory_notes WHERE lead_id=? ORDER BY ts", (lead_id,)),
    }


# ── inbox: live replies come via IMAP; sim replies via this endpoint ─────

@app.post("/api/sim/reply")
async def sim_reply(from_email: str = Form(...), subject: str = Form(""),
                    body: str = Form(...)):
    from .agents import inbox
    result = await asyncio.to_thread(inbox.handle_reply, from_email, subject, body)
    return {"ok": True, **result}


# ── printable lead report ────────────────────────────────────────────────

@app.get("/report/{lead_id}")
async def lead_report(lead_id: str):
    from fastapi.responses import HTMLResponse
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead:
        raise HTTPException(404, "no such lead")
    q = json.loads(lead["score_reasons"]) if lead["score_reasons"] else None
    svc = json.loads(lead["service"]) if lead["service"] else None
    res = json.loads(lead["research"]) if lead["research"] else None
    contacts = db.rows("SELECT * FROM contacts WHERE lead_id=?", (lead_id,))
    evidence = db.rows("SELECT * FROM evidence WHERE lead_id=? LIMIT 10", (lead_id,))
    meetings = db.rows("SELECT * FROM meetings WHERE lead_id=?", (lead_id,))
    profile = db.kv_get("company_profile") or {}

    def rows_html(items):
        return "".join(items)

    factors = rows_html(
        f"<tr><td>{f['name']}</td><td><div class='trk'><i style='width:{f['score']}%'></i></div></td>"
        f"<td class='num'>{f['score']}</td><td class='dim'>{f['reason']}</td></tr>"
        for f in (q["factors"] if q else []))
    ev_html = rows_html(
        f"<div class='ev'><b>{e['meta'] or ''}</b><div class='q'>&ldquo;{e['quote']}&rdquo;</div>"
        f"<div class='u'>{e['url']}</div></div>" for e in evidence)
    ct_html = rows_html(
        f"<tr><td><b>{c['name']}</b></td><td>{c['role']}</td><td>{c['email']}</td>"
        f"<td><span class='tag'>{c['email_status']}</span></td></tr>" for c in contacts)
    mt_html = rows_html(
        f"<p><b>Meeting:</b> {m['status']} &middot; <a href='{m['link']}'>{m['link']}</a></p>"
        for m in meetings)

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Lead report — {lead['name']}</title><style>
body{{font:14px/1.55 'Segoe UI',system-ui,sans-serif;color:#15202e;max-width:820px;margin:40px auto;padding:0 24px}}
.brand{{display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid #0284c7;padding-bottom:12px}}
.brand b{{color:#0284c7}} h1{{margin:18px 0 2px}} .sub{{color:#5b6b80}}
.score{{font-size:2.6rem;font-weight:800;color:{'#059669' if (lead['score'] or 0)>=75 else '#b45309' if (lead['score'] or 0)>=50 else '#dc2626'}}}
h2{{margin:26px 0 8px;font-size:1.02rem;text-transform:uppercase;letter-spacing:.06em;color:#334155;border-bottom:1px solid #e2e8f0;padding-bottom:4px}}
table{{width:100%;border-collapse:collapse}} td{{padding:6px 8px;border-bottom:1px solid #eef2f7;vertical-align:top}}
.num{{font-weight:700}} .dim{{color:#5b6b80;font-size:.86rem}}
.trk{{width:120px;height:7px;background:#eef2f7;border-radius:99px;overflow:hidden}} .trk i{{display:block;height:100%;background:#0284c7}}
.ev{{border-left:3px solid #0284c7;background:#f7fafc;padding:8px 12px;margin:8px 0;border-radius:0 8px 8px 0}}
.ev .q{{font-style:italic}} .ev .u{{color:#94a3b8;font-size:.76rem;word-break:break-all}}
.tag{{border:1px solid #cbd5e1;border-radius:99px;padding:1px 9px;font-size:.72rem;text-transform:uppercase}}
@media print{{body{{margin:10mm}}.noprint{{display:none}}}}
</style></head><body>
<div class="brand"><div><b>Auto</b>SDR &middot; lead intelligence report</div>
<div class="sub">{profile.get('company_name','')} &middot; generated by the autonomous sales agent</div></div>
<h1>{lead['name']}</h1>
<div class="sub">{lead['website'] or ''} &middot; {lead['industry'] or ''} &middot; {lead['location'] or ''} &middot; stage: {lead['stage']}</div>
<div class="score">{lead['score'] if lead['score'] is not None else '—'}%</div>
<div class="sub">{q['headline'] if q else ''}</div>
{'<h2>Why this score</h2><table>' + factors + '</table><p class="dim">' + q['explanation'] + '</p>' if q else ''}
{'<h2>Recommended service</h2><p><b>' + svc['service_name'] + '</b> — ' + svc['why'] + '</p><p class="dim">Proof point: ' + svc['proof_point'] + '</p>' if svc else ''}
{'<h2>Decision makers</h2><table>' + ct_html + '</table>' if contacts else ''}
{'<h2>Research summary</h2><p class="dim">' + res['summary'] + '</p>' if res else ''}
{'<h2>Evidence</h2>' + ev_html if evidence else ''}
{'<h2>Meetings</h2>' + mt_html if meetings else ''}
<p class="noprint" style="margin-top:30px"><button onclick="window.print()" style="padding:10px 22px;font-size:1rem;cursor:pointer">Print / save as PDF</button></p>
</body></html>"""
    return HTMLResponse(html)


# ── booking page (prospect-facing) ───────────────────────────────────────

@app.get("/book/{token}")
async def booking_page(token: str):
    info = db.kv_get(f"booking:{token}")
    if not info:
        raise HTTPException(404, "booking link expired")
    return FileResponse(ROOT / "app" / "static" / "book.html")


@app.get("/api/book/{token}")
async def booking_info(token: str):
    from .tools import meetings as mt
    info = db.kv_get(f"booking:{token}")
    if not info:
        raise HTTPException(404, "booking link expired")
    lead = db.one("SELECT name FROM leads WHERE id=?", (info["lead_id"],))
    profile = db.kv_get("company_profile") or {}
    return {"company": profile.get("company_name", ""), "prospect": lead["name"],
            "slots": mt.slots()}


@app.post("/api/book/{token}")
async def booking_confirm(token: str, slot_utc: float = Form(...)):
    from .tools import meetings as mt
    from .agents import meeting as meeting_agent
    result = mt.finalize(token, slot_utc)
    if not result:
        raise HTTPException(404, "booking link expired")
    await asyncio.to_thread(meeting_agent.on_booked, result)
    return {"ok": True, "link": result["link"], "time_label": result["time_label"]}


@app.get("/api/health")
async def health():
    return {"ok": True, "email_mode": EMAIL_MODE, "whatsapp_mode": WHATSAPP_MODE,
            "seconds_per_day": SECONDS_PER_DAY}


@app.get("/api/events/stream")
async def events_stream():
    q = bus.subscribe()

    async def gen():
        try:
            for evt in bus.recent(100):
                yield f"data: {json.dumps(evt, default=str)}\n\n"
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(evt, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/state")
async def state():
    # deterministic order: ties on updated_ts must not reshuffle between polls
    leads = db.rows("SELECT * FROM leads ORDER BY updated_ts DESC, id")
    for l in leads:
        for f in ("score_reasons", "service", "research"):
            if l.get(f):
                l[f] = json.loads(l[f])
    return {
        "stages": db.STAGES,
        "leads": leads,
        "profile": db.kv_get("company_profile"),
        "icp": db.kv_get("icp"),
        "costs": db.kv_get("costs", {"calls": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0}),
    }


@app.get("/")
async def index():
    return FileResponse(ROOT / "app" / "static" / "index.html",
                        headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
