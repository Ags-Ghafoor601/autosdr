"""QualifierAgent: dossier + ICP -> confidence score with factor-by-factor explanation.

The brief's example: "ABC Logistics — 92% Potential Lead" + WHY.
This agent must be able to say NO (not_qualified) — the goal is best leads,
not most contacts.
"""
import json

from .. import bus, db, llm, memory

QUALIFY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "qualified": {"type": "boolean"},
        "headline": {"type": "string"},
        "factors": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "name": {"type": "string"},
                "score": {"type": "integer", "minimum": 0, "maximum": 100},
                "weight": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["name", "score", "weight", "reason"],
        }},
        "risks": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
    },
    "required": ["score", "qualified", "headline", "factors", "risks", "explanation"],
}

SYSTEM = """You are the Qualification Agent of an autonomous sales system.
Score this prospect 0-100 for fit with the ICP and the selling company's services.
Score factors independently: icp_fit, problem_fit, service_fit, buying_signals,
company_size_fit, location_fit, evidence_quality. Weights should sum to ~1.
Be strict:
- Reward only what the EVIDENCE supports. Thin evidence => low evidence_quality
  and a capped overall score.
- qualified=true only if score >= 60 AND evidence_quality >= 40.
- The explanation must read like a sales analyst's verdict a human can trust.
- It is GOOD to reject: the objective is the best leads, not the most contacts."""


def run_one(lead_id: str, threshold: int = 60) -> dict:
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    assert lead and lead["research"], f"lead {lead_id} not researched"
    icp = db.kv_get("icp")
    profile = db.kv_get("company_profile") or {}
    dossier = json.loads(lead["research"])
    memory.set_task(f"Qualifying {lead['name']}", "qualify")
    bus.emit("qualify", "plan", f"Score {lead['name']} against ICP with per-factor breakdown",
             lead_id=lead_id)

    services = "\n".join(f"- {s['name']}: {s['ideal_for']}" for s in profile.get("services", []))
    verdict = llm.chat(
        SYSTEM,
        f"ICP: {json.dumps(icp, ensure_ascii=False)}\n\n"
        f"OUR SERVICES:\n{services}\n\n"
        f"PROSPECT: {lead['name']} ({lead['website']})\n"
        f"DOSSIER: {json.dumps(dossier, ensure_ascii=False)[:14000]}",
        QUALIFY_SCHEMA, agent="qualify")

    stage = "qualified" if verdict["qualified"] and verdict["score"] >= threshold else "not_qualified"
    db.update("leads", lead_id, {
        "score": verdict["score"],
        "score_reasons": json.dumps(verdict, ensure_ascii=False),
        "updated_ts": db.now(),
    })
    db.set_stage(lead_id, stage)
    memory.remember(lead_id, "qualification",
                    f"{lead['name']} scored {verdict['score']}% ({stage}): {verdict['headline']}")
    bus.emit("qualify", "decision",
             f"{lead['name']} — {verdict['score']}% {'QUALIFIED' if stage=='qualified' else 'NOT QUALIFIED'}"
             f" · {verdict['headline'][:100]}",
             {"factors": verdict["factors"], "risks": verdict["risks"]}, lead_id=lead_id)
    bus.emit("qualify", "stage",
             f"{lead['name']} → {'Qualified' if stage=='qualified' else 'Not Qualified'}",
             lead_id=lead_id)
    memory.set_task(None)
    return verdict
