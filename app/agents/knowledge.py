"""KnowledgeAgent: company PDF/text -> RAG -> structured company profile.

The profile is what every downstream agent grounds on: services (for
service-matching), industries (for ICP sanity), cases (for outreach proof
points), pricing and limitations (for honest replies).
"""
from .. import bus, db, llm, memory, rag

PROFILE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "company_name": {"type": "string"},
        "tagline": {"type": "string"},
        "what_we_sell": {"type": "string"},
        "services": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "ideal_for": {"type": "string"},
                "buying_signals": {"type": "array", "items": {"type": "string"}},
                "source_chunks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name", "description", "ideal_for", "buying_signals", "source_chunks"],
        }},
        "target_industries": {"type": "array", "items": {"type": "string"}},
        "case_studies": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "client": {"type": "string"}, "industry": {"type": "string"},
                "problem": {"type": "string"}, "result": {"type": "string"},
                "source_chunks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["client", "industry", "problem", "result", "source_chunks"],
        }},
        "pricing_notes": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "differentiators": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["company_name", "tagline", "what_we_sell", "services", "target_industries",
                 "case_studies", "pricing_notes", "limitations", "differentiators"],
}

SYSTEM = """You are the Knowledge Agent of an autonomous sales system.
Extract a faithful, structured company profile from the provided document chunks.
Rules:
- Use ONLY facts present in the chunks. Never invent services, clients, numbers or claims.
- Every service and case study must cite the chunk ids it came from (source_chunks).
- If something is not stated (e.g. pricing), say so plainly in that field.
- CONFLICTING/DATED RECORDS: company documents may contain older statements that
  conflict with newer ones (old pricing, 'experimental' features now launched,
  'fully automated' claims superseded by governance rules). Prefer the most recent
  and most authoritative record (current service catalog, current pricing guide,
  governance/security policy). Record superseded claims in limitations as
  "outdated: <claim> — current: <correct record>".
- Include in limitations everything sales must never promise (compliance guarantees,
  zero hallucinations, unrestricted messaging, autonomous high-impact actions).
- Keep descriptions crisp and sales-usable."""


def build_profile(source_name: str, text: str | None = None, pdf_path: str | None = None) -> dict:
    memory.set_task("Understanding the company document", "knowledge")
    bus.emit("knowledge", "plan", "Ingest company doc → build knowledge base → extract structured profile")
    n = rag.ingest(source_name, text=text, pdf_path=pdf_path)
    chunks = db.rows("SELECT id, text FROM kb_chunks ORDER BY idx")
    doc = "\n\n".join(f"[{c['id']}] {c['text']}" for c in chunks)
    if len(doc) > 90_000:  # very large docs: keep head+tail, RAG covers the rest downstream
        doc = doc[:60_000] + "\n\n...[truncated]...\n\n" + doc[-25_000:]
    bus.emit("knowledge", "tool_call", f"extracting structured profile from {n} chunks")
    profile = llm.chat(SYSTEM, f"Company document chunks:\n\n{doc}", PROFILE_SCHEMA, agent="knowledge")
    db.kv_set("company_profile", profile)
    memory.remember(None, "company",
                    f"Profile built for {profile['company_name']}: "
                    f"{len(profile['services'])} services, {len(profile['case_studies'])} case studies")
    bus.emit("knowledge", "decision",
             f"Profile ready: {profile['company_name']} — {len(profile['services'])} services, "
             f"{len(profile['case_studies'])} cases, {len(profile['target_industries'])} industries",
             {"services": [s["name"] for s in profile["services"]]})
    memory.set_task(None)
    return profile
