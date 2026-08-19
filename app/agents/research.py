"""ResearchAgent: deep, evidence-first research on potential leads.

Scrapes the company site (home + about/contact/team), runs targeted news/
funding/hiring searches, then synthesizes a research dossier where every
claim carries evidence (url + quote). No evidence => not a claim.
"""
from .. import bus, db, llm, memory
from ..tools import scrape, serper

RESEARCH_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "what_they_do": {"type": "string"},
        "size_hint": {"type": "string"},
        "technologies": {"type": "array", "items": {"type": "string"}},
        "recent_news": {"type": "array", "items": {"type": "string"}},
        "buying_signals": {"type": "array", "items": {"type": "string"}},
        "likely_problems": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "claim": {"type": "string"},
                "url": {"type": "string"},
                "quote": {"type": "string"},
            },
            "required": ["claim", "url", "quote"],
        }},
    },
    "required": ["summary", "what_they_do", "size_hint", "technologies",
                 "recent_news", "buying_signals", "likely_problems", "evidence"],
}

SYSTEM = """You are the Research Agent of an autonomous sales system.
Synthesize a research dossier for the prospect from the scraped pages and search
results provided. HARD RULES:
- Claims must come from the provided material. Quote the exact supporting text in
  evidence[] (short quotes, <=200 chars) with the source url.
- If the material doesn't support a field, leave it empty / say 'unknown'.
- buying_signals = concrete observations suggesting they need the selling company's
  kind of services (growth, hiring, manual processes, high inquiry volume, outdated
  tech, new market entry...).
- likely_problems = business problems inferable FROM EVIDENCE, phrased carefully."""


def run_one(lead_id: str) -> dict:
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    assert lead, f"no lead {lead_id}"
    profile = db.kv_get("company_profile") or {}
    memory.set_task(f"Deep research: {lead['name']}", "research")
    db.set_stage(lead_id, "researching")
    bus.emit("research", "stage", f"{lead['name']} → Researching", lead_id=lead_id)
    bus.emit("research", "plan",
             f"Scrape site + subpages, search news/funding/hiring, synthesize dossier",
             lead_id=lead_id)

    # 1) scrape home + interesting subpages
    home = scrape.fetch(lead["website"], agent="research")
    pages = [home]
    base = lead["website"].rstrip("/")
    for link in home["links"][:3]:
        url = link if link.startswith("http") else f"{base}/{link.lstrip('/')}"
        if _same_site(url, lead["domain"]):
            pages.append(scrape.fetch(url, agent="research"))
    site_text = "\n\n".join(
        f"=== PAGE {p['url']} ===\n{p['text'][:6000]}" for p in pages if p["ok"])

    # collect contact signals for later stages
    emails = sorted({e for p in pages for e in p["emails"]})
    whatsapp = sorted({w for p in pages for w in p["whatsapp"]})
    if emails or whatsapp:
        memory.set_scratch(lead_id, "scraped_emails", emails)
        memory.set_scratch(lead_id, "scraped_whatsapp", whatsapp)
        bus.emit("research", "step",
                 f"contact signals: {len(emails)} emails, {len(whatsapp)} whatsapp numbers",
                 {"emails": emails, "whatsapp": whatsapp}, lead_id=lead_id)

    # 2) targeted searches
    sr_blocks = []
    for q in (f'"{lead["name"]}" news', f'"{lead["name"]}" funding OR expansion OR growth'):
        rs = serper.search(q, num=5, agent="research")
        sr_blocks += [f"[search:{q}] {r['title']} — {r['snippet']} ({r['link']})" for r in rs]

    # 3) synthesize dossier
    dossier = llm.chat(
        SYSTEM,
        f"Selling company context (what WE sell): {profile.get('what_we_sell','')[:600]}\n\n"
        f"PROSPECT: {lead['name']} ({lead['website']})\n\n"
        f"SCRAPED SITE MATERIAL:\n{site_text[:26000]}\n\n"
        f"SEARCH RESULTS:\n" + "\n".join(sr_blocks[:20]),
        RESEARCH_SCHEMA, agent="research")

    for ev in dossier["evidence"][:12]:
        db.insert("evidence", {"lead_id": lead_id, "kind": "research", "url": ev["url"],
                               "quote": ev["quote"][:400], "meta": ev["claim"][:200], "ts": db.now()})
    if whatsapp:
        dossier["whatsapp_numbers"] = whatsapp
    if emails:
        dossier["scraped_emails"] = emails
    db.update("leads", lead_id, {"research": _json(dossier), "updated_ts": db.now()})
    memory.remember(lead_id, "research",
                    f"{lead['name']}: {dossier['summary'][:180]} | signals: "
                    f"{'; '.join(dossier['buying_signals'][:3])}")
    bus.emit("research", "decision",
             f"Dossier ready for {lead['name']}: {len(dossier['evidence'])} evidence items, "
             f"{len(dossier['buying_signals'])} buying signals", lead_id=lead_id)
    memory.set_task(None)
    return dossier


def _same_site(url: str, domain: str) -> bool:
    return domain in url


def _json(o) -> str:
    import json
    return json.dumps(o, ensure_ascii=False)
