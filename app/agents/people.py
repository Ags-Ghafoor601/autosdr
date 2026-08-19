"""PeopleAgent: find decision-makers relevant to the recommended service.

Sources, in trust order:
1. Emails scraped from the prospect's own site (email_status=scraped)
2. Hunter.io domain search when a key is set (email_status=verified/hunter)
3. Public search results naming executives (role identification)
4. Pattern guess first@domain — ALWAYS flagged email_status=guessed, never
   presented as fact. Honesty over volume.
"""
import json
import re

import httpx

from .. import bus, db, llm, memory
from ..config import HUNTER_API_KEY
from ..tools import serper

PEOPLE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "contacts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "name": {"type": "string"},
                "role": {"type": "string"},
                "email": {"type": "string"},
                "email_status": {"type": "string", "enum": ["scraped", "verified", "guessed", "unknown"]},
                "relevance_reason": {"type": "string"},
            },
            "required": ["name", "role", "email", "email_status", "relevance_reason"],
        }},
    },
    "required": ["contacts"],
}

SYSTEM = """You are the Decision-Maker Agent of an autonomous sales system.
From the material provided, select up to 3 contacts MOST relevant to selling the
recommended service (e.g. CTO for technical products, Head of Support for support
automation, CEO/Founder for small companies).
Rules:
- Only name people the material actually names. Do not invent people.
- Prefer emails found in the material (mark email_status accordingly: 'scraped'
  for site-scraped, 'verified' for Hunter-verified).
- If a named person has no email, you may use the company's general email
  (info@/contact@) with their name, or construct first@domain marked 'guessed'.
- If nobody is named, return the company's general inbox as contact name
  'Team <Company>' with role 'General'."""


def _hunter(domain: str) -> list[dict]:
    if not HUNTER_API_KEY:
        return []
    bus.emit("people", "tool_call", f"hunter.io domain search: {domain}")
    try:
        r = httpx.get("https://api.hunter.io/v2/domain-search",
                      params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": 10},
                      timeout=20)
        r.raise_for_status()
        out = [{"name": f"{e.get('first_name','')} {e.get('last_name','')}".strip(),
                "role": e.get("position") or "", "email": e["value"],
                "confidence": e.get("confidence", 0)}
               for e in r.json().get("data", {}).get("emails", [])]
        bus.emit("people", "tool_result", f"hunter.io: {len(out)} emails for {domain}")
        return out
    except Exception as e:  # noqa: BLE001
        bus.emit("people", "error", f"hunter.io failed: {str(e)[:120]}")
        return []


def run_one(lead_id: str) -> list[dict]:
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    assert lead, f"no lead {lead_id}"
    service = json.loads(lead["service"]) if lead["service"] else {}
    memory.set_task(f"Finding decision makers at {lead['name']}", "people")
    bus.emit("people", "plan",
             f"Locate decision-makers relevant to '{service.get('service_name','(service)')}'",
             lead_id=lead_id)

    scraped = memory.scratch(lead_id).get("scraped_emails", [])
    hunter = _hunter(lead["domain"])
    sr = serper.search(f'"{lead["name"]}" (CEO OR founder OR CTO OR "head of") {lead["location"] or ""}',
                       num=6, agent="people")
    sr_block = "\n".join(f"- {r['title']} — {r['snippet']}" for r in sr)

    out = llm.chat(
        SYSTEM,
        f"PROSPECT: {lead['name']} (domain {lead['domain']})\n"
        f"RECOMMENDED SERVICE: {service.get('service_name','')} — {service.get('why','')[:300]}\n\n"
        f"EMAILS SCRAPED FROM THEIR SITE: {scraped}\n"
        f"HUNTER.IO RESULTS: {json.dumps(hunter, ensure_ascii=False)}\n"
        f"PUBLIC SEARCH RESULTS:\n{sr_block}",
        PEOPLE_SCHEMA, fast=True, agent="people")

    contacts = []
    for c in out["contacts"][:3]:
        if not re.match(r"[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$", c["email"]):
            continue
        cid = db.insert("contacts", {
            "lead_id": lead_id, "name": c["name"], "role": c["role"],
            "email": c["email"].lower(), "email_status": c["email_status"],
            "source": c["relevance_reason"][:200], "ts": db.now(),
        })
        contacts.append({**c, "id": cid})
        bus.emit("people", "decision",
                 f"{lead['name']}: {c['name']} ({c['role']}) <{c['email']}> [{c['email_status']}]",
                 lead_id=lead_id)
    if contacts:
        memory.remember(lead_id, "contacts",
                        f"Decision makers: " + "; ".join(f"{c['name']} ({c['role']})" for c in contacts))
    else:
        bus.emit("people", "error", f"no valid contacts found for {lead['name']}", lead_id=lead_id)
    memory.set_task(None)
    return contacts
