"""InboxAgent: classify prospect replies -> decide + take the next action.

Categories per the brief: positive / meeting_requested / question /
pricing_objection / technical_objection / not_interested / not_now /
wrong_person_referral / other. The classification drives the state machine;
replies to questions/objections are RAG-grounded in the company knowledge.
"""
import json

from .. import bus, db, llm, memory, rag
from ..tools import emailer, meetings

CLASSIFY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "category": {"type": "string",
                     "enum": ["positive", "meeting_requested", "question", "pricing_objection",
                              "technical_objection", "not_interested", "not_now",
                              "wrong_person_referral", "other"]},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "summary": {"type": "string"},
        "extracted_question": {"type": "string"},
        "next_action": {"type": "string"},
    },
    "required": ["category", "sentiment", "summary", "extracted_question", "next_action"],
}

REPLY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
    "required": ["subject", "body"],
}

CLASSIFY_SYSTEM = """You are the Inbox Agent of an autonomous sales system.
Classify the prospect's reply into exactly one category and summarize it.
'meeting_requested' when they want to talk/see a demo/pick a time.
'question' for info requests; objections split into pricing vs technical.
next_action: one short sentence describing what the system should do now."""

REPLY_SYSTEM = """You are the Inbox Agent replying on behalf of {company}.
Write a short (60-110 words), specific reply email.
- Answer questions/objections ONLY from the provided company knowledge (RAG chunks).
  If the knowledge doesn't cover it, say you'll confirm details on a quick call —
  never invent pricing, features, or claims.
- Keep the thread's context (their reply is provided).
- If appropriate, restate the booking link on its own line.
- Sign as {sender}, {company}. Plain text."""


def handle_reply(from_addr: str, subject: str, body: str, sender_name: str = "Tehseen") -> dict:
    contact = db.one("SELECT * FROM contacts WHERE email=? ORDER BY ts DESC", (from_addr.lower(),))
    if not contact:
        # Sandbox/redirect inbox replying on behalf of a prospect: attribute by
        # thread subject first, else the most recently contacted lead.
        base = subject
        for p in ("re:", "fwd:", "fw:"):
            if base.lower().startswith(p):
                base = base[len(p):].strip()
        m = db.one("SELECT * FROM messages WHERE direction='out' AND channel LIKE 'email%' "
                   "AND subject LIKE ? ORDER BY ts DESC", (f"%{base[:60]}%",)) if base else None
        if not m:
            m = db.one("SELECT * FROM messages WHERE direction='out' AND channel LIKE 'email%' "
                       "AND lead_id IS NOT NULL ORDER BY ts DESC")
        if m and m["contact_id"]:
            contact = db.one("SELECT * FROM contacts WHERE id=?", (m["contact_id"],))
        elif m and m["lead_id"]:
            contact = db.one("SELECT * FROM contacts WHERE lead_id=? ORDER BY ts LIMIT 1",
                             (m["lead_id"],))
        if contact:
            bus.emit("inbox", "step",
                     f"reply from sandbox {from_addr} attributed to "
                     f"{contact['name']} via thread subject", lead_id=contact["lead_id"])
    lead = db.one("SELECT * FROM leads WHERE id=?", (contact["lead_id"],)) if contact else None
    lead_id = lead["id"] if lead else None
    db.insert("messages", {"lead_id": lead_id, "contact_id": contact["id"] if contact else None,
                           "direction": "in", "channel": "email", "subject": subject,
                           "body": body, "meta": None, "status": "received", "ts": db.now()})
    memory.set_task(f"Classifying reply from {from_addr}", "inbox")
    bus.emit("inbox", "plan", f"Classify reply from {from_addr} and decide next action",
             lead_id=lead_id)

    cls = llm.chat(CLASSIFY_SYSTEM,
                   f"Prospect reply from {from_addr} "
                   f"({(contact or {}).get('role','unknown role')} at {(lead or {}).get('name','unknown')}):\n"
                   f"Subject: {subject}\n\n{body[:3000]}",
                   CLASSIFY_SCHEMA, fast=True, agent="inbox")
    bus.emit("inbox", "decision",
             f"reply classified: {cls['category'].upper()} ({cls['sentiment']}) — {cls['summary'][:110]}",
             cls, lead_id=lead_id)
    if lead_id:
        memory.remember(lead_id, "reply", f"{cls['category']}: {cls['summary'][:180]}")
        _cancel_followups(lead_id)  # a reply supersedes the no-reply follow-up

    action = {"category": cls["category"], "replied": False}
    if not lead_id:
        memory.set_task(None)
        return action

    cat = cls["category"]
    if cat in ("positive", "meeting_requested"):
        db.set_stage(lead_id, "interested")
        bus.emit("inbox", "stage", f"{lead['name']} → Interested", lead_id=lead_id)
        action["replied"] = _reply(lead, contact, body, cls, sender_name,
                                   include_booking=True)
    elif cat in ("question", "pricing_objection", "technical_objection"):
        db.set_stage(lead_id, "interested")
        bus.emit("inbox", "stage", f"{lead['name']} → Interested", lead_id=lead_id)
        action["replied"] = _reply(lead, contact, body, cls, sender_name,
                                   include_booking=True, use_rag=True)
    elif cat == "not_interested":
        db.set_stage(lead_id, "not_interested")
        bus.emit("inbox", "stage", f"{lead['name']} → Not Interested", lead_id=lead_id)
        action["replied"] = _reply(lead, contact, body, cls, sender_name, closing=True)
    elif cat == "not_now":
        due = db.now() + 30 * (db.kv_get("seconds_per_day") or _spd())
        db.insert("followups", {"lead_id": lead_id, "due_ts": due, "kind": "not_now_checkin",
                                "status": "scheduled", "meta": None, "ts": db.now()})
        bus.emit("followup", "step", f"{lead['name']}: 'not now' — check-in scheduled (+30 days)",
                 lead_id=lead_id)
        action["replied"] = _reply(lead, contact, body, cls, sender_name, closing=True)
    elif cat == "wrong_person_referral":
        action["replied"] = _reply(lead, contact, body, cls, sender_name,
                                   ask_referral=True)
    memory.set_task(None)
    return action


def _reply(lead, contact, their_body, cls, sender_name, *, include_booking=False,
           use_rag=False, closing=False, ask_referral=False) -> bool:
    profile = db.kv_get("company_profile") or {}
    kb = rag.context_block(cls["extracted_question"] or cls["summary"], k=5) if use_rag else ""
    booking = meetings.booking_link(lead["id"], contact["id"]) if include_booking else ""
    service = json.loads(lead["service"])["service_name"] if lead["service"] else ""
    hist = memory.recall(lead["id"])[:3000]
    instructions = []
    if include_booking:
        instructions.append(f"Include this booking link on its own line: {booking}")
    if closing:
        instructions.append("They declined/deferred — thank them briefly, leave the door open, "
                            "no booking link, no pushiness.")
    if ask_referral:
        instructions.append("Politely ask to be pointed to the right person for "
                            f"{service or 'this'}.")
    out = llm.chat(
        REPLY_SYSTEM.replace("{company}", profile.get("company_name", "our company"))
                    .replace("{sender}", sender_name),
        f"CONTEXT / MEMORY:\n{hist}\n\n"
        f"COMPANY KNOWLEDGE (only source of factual answers):\n{kb[:8000]}\n\n"
        f"THEIR REPLY:\n{their_body[:2000]}\n\n"
        f"CLASSIFICATION: {cls['category']} — {cls['summary']}\n"
        f"QUESTION TO ANSWER: {cls['extracted_question'] or '(none)'}\n"
        + "\n".join(instructions),
        REPLY_SCHEMA, agent="inbox")
    emailer.send(contact["email"], out["subject"], out["body"],
                 lead_id=lead["id"], contact_id=contact["id"],
                 meta={"kind": f"reply_{cls['category']}"})
    memory.remember(lead["id"], "sent_reply", f"Replied to {cls['category']}: {out['subject']}")
    return True


def _cancel_followups(lead_id: str):
    with db.tx() as c:
        c.execute("UPDATE followups SET status='cancelled' "
                  "WHERE lead_id=? AND status='scheduled' AND kind='no_reply_followup'", (lead_id,))
    bus.emit("followup", "step", "pending no-reply follow-up cancelled (reply received)",
             lead_id=lead_id)


def _spd() -> float:
    from ..config import SECONDS_PER_DAY
    return SECONDS_PER_DAY
