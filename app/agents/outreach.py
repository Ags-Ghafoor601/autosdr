"""OutreachAgent: role-personalized, evidence-grounded first-touch emails.

Anti-hallucination by construction: the composer receives ONLY stored evidence
quotes and the RAG-grounded service match. It is instructed to reference facts
solely from that material — and the evidence used is displayed with the email
in the UI, so grounding is inspectable.
"""
import json

from .. import bus, db, llm, memory
from ..tools import emailer, meetings

EMAIL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "personalization_points": {"type": "array", "items": {"type": "string"}},
        "evidence_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["subject", "body", "personalization_points", "evidence_used"],
}

SYSTEM = """You are the Outreach Agent of an autonomous sales system writing a
first-touch B2B email.
Rules:
- 90-140 words. Plain text. No buzzwords, no hype, no 'I hope this finds you well'.
- Personalize to the ROLE: CTO => technical fit/integrations; CEO/Founder => growth,
  cost, risk; Head of Support => workload, response times; Sales => revenue,
  conversion.
- Reference ONLY facts from the provided evidence/dossier. Every company-specific
  claim you make must be traceable to the material; list which evidence you used in
  evidence_used. NEVER invent metrics, events, or details about the prospect.
- One clear proof point about the selling company (from the service match).
- End with a low-friction CTA offering the booking link on its own line:
  'Pick a time that suits you: {booking_link}'
- Sign as {sender_name}, {selling_company}. No placeholders left in the text."""


def run_one(lead_id: str, sender_name: str = "Tehseen") -> list[dict]:
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    assert lead and lead["service"], f"lead {lead_id} has no service match"
    profile = db.kv_get("company_profile") or {}
    service = json.loads(lead["service"])
    dossier = json.loads(lead["research"]) if lead["research"] else {}
    contacts = db.rows("SELECT * FROM contacts WHERE lead_id=?", (lead_id,))
    if not contacts:
        bus.emit("outreach", "error", f"{lead['name']}: no contacts to email", lead_id=lead_id)
        return []
    evidence = db.rows("SELECT url, quote, meta FROM evidence WHERE lead_id=? LIMIT 12", (lead_id,))
    memory.set_task(f"Composing outreach for {lead['name']}", "outreach")
    bus.emit("outreach", "plan",
             f"Compose role-personalized emails for {len(contacts)} contact(s) at {lead['name']}",
             lead_id=lead_id)

    sent = []
    last_booking = ""
    for c in contacts:
        booking = last_booking = meetings.booking_link(lead_id, c["id"])
        out = llm.chat(
            SYSTEM.replace("{booking_link}", booking)
                  .replace("{sender_name}", sender_name)
                  .replace("{selling_company}", profile.get("company_name", "our company")),
            f"SELLING COMPANY: {profile.get('company_name','')} — {profile.get('what_we_sell','')[:400]}\n"
            f"RECOMMENDED SERVICE for this prospect: {service['service_name']}\n"
            f"WHY: {service['why']}\nPROOF POINT: {service['proof_point']}\n"
            f"PITCH ANGLE: {service['pitch_angle']}\n\n"
            f"PROSPECT: {lead['name']} ({lead['website']})\n"
            f"THEIR LIKELY PROBLEM: {service['prospect_problem']}\n"
            f"RECIPIENT: {c['name']} — role: {c['role']}\n\n"
            f"EVIDENCE (the ONLY prospect facts you may reference):\n"
            + "\n".join(f"- {e['meta'] or ''}: \"{e['quote'][:200]}\" ({e['url']})" for e in evidence)
            + f"\n\nDOSSIER SUMMARY: {dossier.get('summary','')[:500]}\n\n"
            f"Include this booking link verbatim: {booking}",
            EMAIL_SCHEMA, agent="outreach")
        res = emailer.send_or_queue(c["email"], out["subject"], out["body"],
                                    lead_id=lead_id, contact_id=c["id"],
                                    meta={"role": c["role"], "service": service["service_name"],
                                          "score": lead["score"], "booking_link": booking,
                                          "personalization": out["personalization_points"],
                                          "evidence_used": out["evidence_used"], "kind": "outreach_1"})
        sent.append({"contact": c["name"], "email": c["email"], **res})
        memory.remember(lead_id, "outreach",
                        f"Email #1 to {c['name']} ({c['role']}): '{out['subject']}' — "
                        f"service {service['service_name']}, booking {booking}")
    # EXTRA: if the company exposes a WhatsApp number, message them there too
    # (allowlist-guarded: real company numbers auto-route to the simulated channel)
    wa_numbers = dossier.get("whatsapp_numbers") or []
    if wa_numbers and sent:
        from ..tools import whatsapp as wa
        wa.send(f"+{wa_numbers[0]}",
                f"Assalam o alaikum — {sender_name} here from {profile.get('company_name','')}. "
                f"We help {lead['name']}-type operations automate "
                f"{service['prospect_problem'][:120]}. Just emailed the details — "
                f"happy to walk you through it. Book directly: {last_booking}".strip(),
                lead_id=lead_id, kind="company_outreach")

    db.set_stage(lead_id, "contacted")
    bus.emit("outreach", "stage", f"{lead['name']} → Contacted", lead_id=lead_id)

    # schedule the 3-day follow-up (demo clock scales this)
    from ..config import followup_delay_seconds
    due = db.now() + followup_delay_seconds()
    db.insert("followups", {"lead_id": lead_id, "due_ts": due, "kind": "no_reply_followup",
                            "status": "scheduled", "meta": None, "ts": db.now()})
    bus.emit("followup", "step",
             f"{lead['name']}: follow-up scheduled (Day 0 → wait 3 'days' → Email #2)",
             lead_id=lead_id)
    memory.set_task(None)
    return sent
