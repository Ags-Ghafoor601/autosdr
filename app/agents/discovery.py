"""DiscoveryAgent: ICP search queries -> candidates -> CHEAP FILTER -> potential leads.

Staged exactly as the brief requires:
  Search -> Cheap Filtering -> Potential Leads   (deep research happens later, only for keepers)

Cheap filter = one fast-model pass over name+snippet only. No scraping, no
deep calls — obviously-irrelevant candidates die here for fractions of a cent.
"""
import re
from urllib.parse import urlparse

from .. import bus, db, llm, memory
from ..tools import serper

FILTER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "decisions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "index": {"type": "integer"},
                "keep": {"type": "boolean"},
                "company_name": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["index", "keep", "company_name", "reason"],
        }},
    },
    "required": ["decisions"],
}

FILTER_SYSTEM = """You are the Cheap Filter of an autonomous sales system.
You see ONLY search-result titles/snippets/domains. Decide keep/drop per candidate.
DROP: directories, aggregators, job boards, news sites, social platforms, marketplaces
(clutch/upwork/linkedin/glassdoor/yelp/wikipedia etc.), government/edu, obvious ICP
mismatches (wrong geography/industry), and the selling company itself.
KEEP: real operating companies that plausibly match the ICP. When unsure on a real
company, keep it — deep research will settle it. Extract a clean company_name."""

_BAD_DOMAINS = (
    "linkedin.", "facebook.", "instagram.", "twitter.", "x.com", "youtube.", "wikipedia.",
    "clutch.co", "upwork.", "fiverr.", "glassdoor.", "indeed.", "crunchbase.", "yelp.",
    "google.", "medium.", "reddit.", "quora.", "amazon.", "apple.com", "play.google",
    "tripadvisor.", "yellowpages", "justdial", "sortlist", "goodfirms", "designrush",
)


def _domain(url: str) -> str:
    try:
        d = urlparse(url).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:  # noqa: BLE001
        return ""


def run(max_queries: int = 6, per_query: int = 10) -> dict:
    icp = db.kv_get("icp")
    assert icp, "ICP not set"
    profile = db.kv_get("company_profile") or {}
    own_domain = _domain(profile.get("website", "") or "")
    memory.set_task("Discovering leads (search → cheap filter)", "discovery")
    bus.emit("discovery", "plan",
             f"Run {min(max_queries, len(icp['search_queries']))} ICP search queries, "
             f"dedupe by domain, cheap-filter on snippets only")

    # 1) SEARCH
    seen: dict[str, dict] = {}
    for q in icp["search_queries"][:max_queries]:
        for r in serper.search(q, num=per_query):
            d = _domain(r["link"])
            if not d or d == own_domain or any(b in d for b in _BAD_DOMAINS):
                continue
            root = f"https://{d}"
            if d not in seen:
                seen[d] = {"domain": d, "website": root, "titles": [], "snippets": []}
            seen[d]["titles"].append(r["title"])
            seen[d]["snippets"].append(r["snippet"])
    candidates = list(seen.values())
    bus.emit("discovery", "step", f"{len(candidates)} unique company domains after search + domain scrub")
    if not candidates:
        memory.set_task(None)
        return {"searched": 0, "kept": 0, "dropped": 0}

    # 2) CHEAP FILTER (fast model, snippets only, batched)
    kept, dropped = 0, 0
    for batch_start in range(0, len(candidates), 20):
        batch = candidates[batch_start:batch_start + 20]
        listing = "\n".join(
            f"{i}. domain: {c['domain']} | title: {c['titles'][0][:100]} | "
            f"snippet: {(c['snippets'][0] or '')[:200]}"
            for i, c in enumerate(batch))
        out = llm.chat(
            FILTER_SYSTEM,
            f"ICP: industries={icp['industries']} location={icp['location']} "
            f"size={icp['company_size']} focus={icp['special_targeting']}\n"
            f"Disqualifiers: {icp['disqualifiers']}\n\nCandidates:\n{listing}",
            FILTER_SCHEMA, fast=True, agent="discovery")
        for d in out["decisions"]:
            if not (0 <= d["index"] < len(batch)):
                continue
            c = batch[d["index"]]
            name = re.sub(r"\s*[|–-].*$", "", d["company_name"]).strip() or c["domain"]
            if d["keep"]:
                if db.one("SELECT id FROM leads WHERE domain=?", (c["domain"],)):
                    continue
                lead_id = db.insert("leads", {
                    "name": name, "domain": c["domain"], "website": c["website"],
                    "location": icp["location"], "industry": ", ".join(icp["industries"][:2]),
                    "source": "web_search", "stage": "potential",
                    "created_ts": db.now(), "updated_ts": db.now(),
                })
                db.insert("evidence", {
                    "lead_id": lead_id, "kind": "search_snippet", "url": c["website"],
                    "quote": (c["snippets"][0] or c["titles"][0])[:400],
                    "meta": None, "ts": db.now(),
                })
                bus.emit("discovery", "decision", f"KEEP {name} — {d['reason'][:120]}",
                         lead_id=lead_id)
                bus.emit("discovery", "stage", f"{name} → Potential", lead_id=lead_id)
                kept += 1
            else:
                bus.emit("discovery", "decision", f"drop {d['company_name'][:60]} — {d['reason'][:100]}")
                dropped += 1
    memory.remember(None, "discovery", f"Discovery run: {len(candidates)} candidates, kept {kept}, dropped {dropped}")
    memory.set_task(None)
    return {"searched": len(candidates), "kept": kept, "dropped": dropped}
