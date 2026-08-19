"""MeetingAgent: when a prospect books — confirm to the prospect with the fixed
time + link, alert the admin on WhatsApp, store everything in memory, and
schedule the 30-minute pre-meeting reminder with an LLM-composed briefing
(problem, service, objections, talking points) recalled from long-term memory.
"""
import json
from datetime import datetime, timedelta, timezone

from .. import bus, db, llm, memory
from ..config import reminder_lead_seconds
from ..tools import emailer, whatsapp

BRIEFING_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "customer_problem": {"type": "string"},
        "recommended_service": {"type": "string"},
        "likely_objections": {"type": "array", "items": {"type": "string"}},
        "key_points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["customer_problem", "recommended_service", "likely_objections", "key_points"],
}

SYSTEM = """You are the Meeting Agent. Compose a compact pre-meeting briefing for the
admin from the lead's memory. Only use facts present in the material. 3-4 likely
objections and 3-5 key talking points, each a short phrase."""


def on_booked(info: dict, sender_name: str = "Tehseen"):
    """info from meetings.finalize(): meeting_id, lead_id, contact_id, time_utc, time_label, link"""
    lead = db.one("SELECT * FROM leads WHERE id=?", (info["lead_id"],))
    contact = db.one("SELECT * FROM contacts WHERE id=?", (info.get("contact_id"),)) \
        if info.get("contact_id") else \
        db.one("SELECT * FROM contacts WHERE lead_id=? ORDER BY ts LIMIT 1", (info["lead_id"],))
    profile = db.kv_get("company_profile") or {}
    memory.set_task(f"Meeting workflow for {lead['name']}", "meeting")

    # 1) stage + memory
    db.set_stage(lead["id"], "meeting_scheduled")
    bus.emit("meeting", "stage", f"{lead['name']} → Meeting Scheduled", lead_id=lead["id"])
    memory.remember(lead["id"], "meeting",
                    f"Meeting booked: {info['time_label']} — {info['link']}")

    # 2) confirm to prospect (fixed time + link, per brief §12)
    if contact:
        emailer.send(
            contact["email"],
            f"Confirmed: {profile.get('company_name','')} × {lead['name']} — {info['time_label']}",
            f"Hi {contact['name'].split()[0] if contact['name'] else 'there'},\n\n"
            f"Great — locked in. Here are the details:\n\n"
            f"When: {info['time_label']}\n"
            f"Where: {info['link']}\n\n"
            f"We'll walk through how we'd approach this for {lead['name']} and answer "
            f"any questions.\n\n{sender_name}\n{profile.get('company_name','')}",
            lead_id=lead["id"], contact_id=contact["id"],
            meta={"kind": "meeting_confirmation", "meeting_id": info["meeting_id"]})

    # 3) admin WhatsApp alert (brief §13)
    service = json.loads(lead["service"])["service_name"] if lead["service"] else "-"
    whatsapp.send_admin(
        f"📅 Meeting booked!\n"
        f"Company: {lead['name']} ({lead['score']}% lead)\n"
        f"Contact: {(contact or {}).get('name','?')} — {(contact or {}).get('role','?')}\n"
        f"Service: {service}\n"
        f"When: {info['time_label']}\n"
        f"Link: {info['link']}",
        lead_id=lead["id"], kind="meeting_booked")

    # 4) schedule 30-min-before reminder with briefing.
    # On the demo clock the whole wait-until-meeting is scaled too, so a meeting
    # tomorrow morning is ~a minute away and the reminder fires on camera.
    from ..config import SECONDS_PER_DAY
    scale = SECONDS_PER_DAY / 86400.0
    remind_at = db.now() + (info["time_utc"] - db.now()) * scale - reminder_lead_seconds()
    db.insert("followups", {"lead_id": lead["id"], "due_ts": max(remind_at, db.now() + 5),
                            "kind": "meeting_reminder", "status": "scheduled",
                            "meta": json.dumps({"meeting_id": info["meeting_id"]}), "ts": db.now()})
    bus.emit("meeting", "step",
             f"reminder scheduled 30 min before ({_fmt(remind_at)})", lead_id=lead["id"])
    memory.set_task(None)


def send_reminder(followup: dict, admin_also_link: bool = True):
    meta = json.loads(followup["meta"] or "{}")
    meeting = db.one("SELECT * FROM meetings WHERE id=?", (meta.get("meeting_id"),))
    lead = db.one("SELECT * FROM leads WHERE id=?", (followup["lead_id"],))
    if not (meeting and lead):
        db.update("followups", followup["id"], {"status": "failed"})
        return
    memory.set_task(f"Pre-meeting briefing for {lead['name']}", "meeting")
    bus.emit("meeting", "plan", f"Compose 30-min reminder briefing for {lead['name']} from memory",
             lead_id=lead["id"])
    briefing = llm.chat(SYSTEM, f"LEAD MEMORY:\n{memory.recall(lead['id'])[:4000]}",
                        BRIEFING_SCHEMA, fast=True, agent="meeting")
    db.update("meetings", meeting["id"], {"briefing": json.dumps(briefing, ensure_ascii=False)})
    label = _fmt(meeting["time_utc"])
    txt = (f"⏰ Meeting in 30 min — {lead['name']} ({label})\n"
           f"{'Link: ' + meeting['link'] if admin_also_link else ''}\n\n"
           f"Problem: {briefing['customer_problem'][:180]}\n"
           f"Pitch: {briefing['recommended_service'][:120]}\n"
           f"Objections: " + "; ".join(briefing["likely_objections"][:3]) + "\n"
           f"Key points: " + "; ".join(briefing["key_points"][:4]))
    whatsapp.send_admin(txt, lead_id=lead["id"], kind="meeting_reminder")
    db.update("followups", followup["id"], {"status": "done"})
    memory.remember(lead["id"], "reminder", f"Admin briefed 30 min before meeting ({label})")
    memory.set_task(None)


def _fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone(timedelta(hours=5))).strftime("%d %b %I:%M %p PKT")
