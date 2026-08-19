"""FollowUpAgent: Day 0 -> Email #1 -> wait 3 'days' -> Email #2.

Fires from the scheduler when a followup comes due and the lead still hasn't
replied. Email #2 is composed from long-term memory (it knows exactly what
Email #1 said) — shorter, adds one new angle, restates the booking link.
"""
import json

from .. import bus, db, llm, memory
from ..tools import emailer, meetings

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"},
                   "new_angle": {"type": "string"}},
    "required": ["subject", "body", "new_angle"],
}

SYSTEM = """You are the Follow-Up Agent of an autonomous sales system.
Write follow-up Email #2 to a prospect who did not reply to Email #1.
- 50-90 words, plain text, same thread tone ('Re:' subject reusing Email #1 subject).
- Do NOT guilt-trip ('just bumping this'). Add ONE new concrete angle from the
  provided material (a different proof point, a sharper problem statement, or a
  relevant capability) — never invent prospect facts.
- Restate the booking link on its own line.
- Sign as {sender}, {company}."""


def run_due(followup: dict, sender_name: str = "Tehseen") -> bool:
    lead = db.one("SELECT * FROM leads WHERE id=?", (followup["lead_id"],))
    if not lead:
        return False
    # replied since? then this follow-up is moot
    replied = db.one("SELECT id FROM messages WHERE lead_id=? AND direction='in'", (lead["id"],))
    if replied or lead["stage"] in ("interested", "meeting_scheduled", "converted",
                                    "not_interested", "do_not_contact"):
        db.update("followups", followup["id"], {"status": "skipped"})
        bus.emit("followup", "step", f"{lead['name']}: follow-up skipped (state moved on)",
                 lead_id=lead["id"])
        return False

    memory.set_task(f"Follow-up for {lead['name']}", "followup")
    bus.emit("followup", "plan", f"3-day window elapsed with no reply from {lead['name']} — "
                                 f"composing Email #2", lead_id=lead["id"])
    contact = db.one("SELECT * FROM contacts WHERE lead_id=? ORDER BY ts LIMIT 1", (lead["id"],))
    if not contact:
        db.update("followups", followup["id"], {"status": "failed"})
        return False
    profile = db.kv_get("company_profile") or {}
    service = json.loads(lead["service"]) if lead["service"] else {}
    first = db.one("SELECT subject, body, meta FROM messages WHERE lead_id=? AND direction='out' "
                   "AND channel LIKE 'email%' ORDER BY ts LIMIT 1", (lead["id"],))
    booking = meetings.booking_link(lead["id"], contact["id"])

    out = llm.chat(
        SYSTEM.replace("{sender}", sender_name)
              .replace("{company}", profile.get("company_name", "our company")),
        f"MEMORY OF THIS LEAD:\n{memory.recall(lead['id'])[:2500]}\n\n"
        f"EMAIL #1 (already sent):\nSubject: {(first or {}).get('subject','')}\n"
        f"{(first or {}).get('body','')[:1200]}\n\n"
        f"SERVICE MATCH: {service.get('service_name','')} — {service.get('why','')[:300]}\n"
        f"AVAILABLE PROOF POINTS: {service.get('proof_point','')}\n"
        f"Booking link (include verbatim): {booking}",
        SCHEMA, agent="followup")

    emailer.send_or_queue(contact["email"], out["subject"], out["body"],
                          lead_id=lead["id"], contact_id=contact["id"],
                          meta={"kind": "followup_2", "new_angle": out["new_angle"]})
    db.update("followups", followup["id"], {"status": "done"})
    memory.remember(lead["id"], "followup", f"Email #2 sent, angle: {out['new_angle'][:140]}")
    bus.emit("followup", "decision", f"{lead['name']}: follow-up Email #2 sent "
                                     f"(angle: {out['new_angle'][:80]})", lead_id=lead["id"])
    memory.set_task(None)
    return True
