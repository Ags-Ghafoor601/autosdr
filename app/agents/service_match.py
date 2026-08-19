"""ServiceMatcher: pick the ONE service from the company's catalog that best fits
this prospect — grounded in RAG chunks (citations) + the research dossier.

The brief's example: high WhatsApp inquiry volume => recommend the WhatsApp
AI chatbot, not something else.
"""
import json

from .. import bus, db, llm, memory, rag

MATCH_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "service_name": {"type": "string"},
        "why": {"type": "string"},
        "prospect_problem": {"type": "string"},
        "proof_point": {"type": "string"},
        "pitch_angle": {"type": "string"},
        "source_chunks": {"type": "array", "items": {"type": "string"}},
        "runner_up": {"type": "string"},
    },
    "required": ["service_name", "why", "prospect_problem", "proof_point",
                 "pitch_angle", "source_chunks", "runner_up"],
}

SYSTEM = """You are the Service Matching Agent of an autonomous sales system.
Pick exactly ONE service from OUR catalog for this prospect.
- Ground the choice in the prospect's evidenced problems/signals AND in what our
  company actually offers (RAG chunks provided; cite chunk ids in source_chunks).
- proof_point: the most relevant case study or capability FROM THE RAG CHUNKS
  (name the client/industry if present). If none fits, say 'no direct case study'.
- pitch_angle: one sentence for how to open the conversation.
- Never recommend anything not present in the catalog."""


def run_one(lead_id: str) -> dict:
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    assert lead and lead["research"], f"lead {lead_id} not researched"
    profile = db.kv_get("company_profile") or {}
    dossier = json.loads(lead["research"])
    memory.set_task(f"Matching service for {lead['name']}", "service_match")
    bus.emit("service_match", "plan", f"Pick best-fit service for {lead['name']} from catalog",
             lead_id=lead_id)

    query = (f"service for: {'; '.join(dossier.get('likely_problems', [])[:3])} "
             f"{'; '.join(dossier.get('buying_signals', [])[:3])}")
    kb = rag.context_block(query, k=6)
    catalog = "\n".join(
        f"- {s['name']}: {s['description'][:200]} | ideal for: {s['ideal_for'][:150]}"
        for s in profile.get("services", []))

    match = llm.chat(
        SYSTEM,
        f"OUR CATALOG:\n{catalog}\n\n"
        f"RELEVANT RAG CHUNKS (cite these ids):\n{kb[:10000]}\n\n"
        f"PROSPECT {lead['name']} DOSSIER:\n{json.dumps(dossier, ensure_ascii=False)[:8000]}",
        MATCH_SCHEMA, agent="service_match")

    db.update("leads", lead_id, {"service": json.dumps(match, ensure_ascii=False),
                                 "updated_ts": db.now()})
    memory.remember(lead_id, "service",
                    f"Recommend '{match['service_name']}' for {lead['name']}: {match['why'][:150]}")
    bus.emit("service_match", "decision",
             f"{lead['name']} ← {match['service_name']} · {match['why'][:110]}",
             {"proof_point": match["proof_point"], "cites": match["source_chunks"]},
             lead_id=lead_id)
    memory.set_task(None)
    return match
