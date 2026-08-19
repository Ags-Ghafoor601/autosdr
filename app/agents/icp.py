"""ICPAgent: user's targeting answers -> structured Ideal Customer Profile.

The ICP drives everything: search queries for discovery, keep/drop rules for
cheap filtering, and the scoring rubric used at qualification.
"""
from .. import bus, db, llm, memory

ICP_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "location": {"type": "string"},
        "industries": {"type": "array", "items": {"type": "string"}},
        "company_size": {"type": "string"},
        "special_targeting": {"type": "string"},
        "must_have": {"type": "array", "items": {"type": "string"}},
        "disqualifiers": {"type": "array", "items": {"type": "string"}},
        "search_queries": {"type": "array", "items": {"type": "string"},
                            "description": "6-10 diverse web queries to find matching companies"},
        "scoring_hints": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["location", "industries", "company_size", "special_targeting",
                 "must_have", "disqualifiers", "search_queries", "scoring_hints"],
}

SYSTEM = """You are the ICP Agent of an autonomous sales system.
Convert the user's targeting answers into a precise, actionable Ideal Customer Profile.
Ground it in what the selling company actually offers (profile provided).
search_queries must be realistic Google queries that surface COMPANY WEBSITES and
directories in the target location/industry (mix plain queries, 'top X in Y' lists,
directory-style queries). Avoid queries that only return news or job posts.
disqualifiers = concrete reasons to drop a candidate early (wrong geography, consumer-only,
competitor, too small, aggregator/directory site, etc.)."""


def build_icp(answers: dict) -> dict:
    memory.set_task("Structuring the Ideal Customer Profile", "icp")
    profile = db.kv_get("company_profile") or {}
    services = "; ".join(s["name"] for s in profile.get("services", []))
    bus.emit("icp", "plan", "Convert targeting answers into structured ICP + search strategy")
    icp = llm.chat(
        SYSTEM,
        f"Selling company: {profile.get('company_name','(unknown)')} — services: {services}\n"
        f"What we sell: {profile.get('what_we_sell','')}\n\n"
        f"User targeting answers:\n"
        f"- Target location: {answers.get('location','')}\n"
        f"- Target industry/market: {answers.get('industry','')}\n"
        f"- Company size / criteria: {answers.get('size','')}\n"
        f"- Special targeting (problem/use case/service): {answers.get('targeting','')}",
        ICP_SCHEMA, agent="icp",
    )
    db.kv_set("icp", icp)
    memory.remember(None, "icp",
                    f"ICP set: {icp['industries']} in {icp['location']}, size {icp['company_size']}; "
                    f"focus: {icp['special_targeting'][:120]}")
    bus.emit("icp", "decision",
             f"ICP ready: {', '.join(icp['industries'])} · {icp['location']} · {icp['company_size']}",
             {"queries": icp["search_queries"], "disqualifiers": icp["disqualifiers"]})
    memory.set_task(None)
    return icp
