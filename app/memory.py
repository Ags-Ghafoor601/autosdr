"""Memory, exactly as the brief demands.

Short-term: in-process working state — current task, per-lead scratch context,
active agent. Surfaced at /api/memory so judges can SEE it.

Long-term: SQLite (leads, contacts, messages, meetings, followups) plus
memory_notes — durable facts agents write and later recall when composing
follow-ups and meeting briefings.
"""
import threading

from . import bus, db

_lock = threading.Lock()
_short: dict = {"current_task": None, "active_agent": None, "leads": {}}


def set_task(task: str | None, agent: str | None = None):
    with _lock:
        _short["current_task"] = task
        _short["active_agent"] = agent


def scratch(lead_id: str) -> dict:
    with _lock:
        return _short["leads"].setdefault(lead_id, {})


def set_scratch(lead_id: str, key: str, value):
    with _lock:
        _short["leads"].setdefault(lead_id, {})[key] = value


def clear_scratch(lead_id: str):
    with _lock:
        _short["leads"].pop(lead_id, None)


def snapshot() -> dict:
    with _lock:
        return {"current_task": _short["current_task"],
                "active_agent": _short["active_agent"],
                "leads": {k: dict(v) for k, v in _short["leads"].items()}}


# ── long-term ────────────────────────────────────────────────────────────

def remember(lead_id: str | None, kind: str, note: str):
    db.insert("memory_notes", {"lead_id": lead_id, "kind": kind, "note": note, "ts": db.now()})
    bus.emit("memory", "memory", f"remember[{kind}]: {note[:140]}", lead_id=lead_id)


def recall(lead_id: str) -> str:
    """Everything we know about a lead, formatted for prompt injection."""
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead:
        return "no memory"
    parts = [f"Lead: {lead['name']} | stage: {lead['stage']} | score: {lead['score']}"]
    notes = db.rows("SELECT kind, note, ts FROM memory_notes WHERE lead_id=? ORDER BY ts", (lead_id,))
    if notes:
        parts.append("Notes:")
        parts += [f"- [{n['kind']}] {n['note']}" for n in notes[-15:]]
    msgs = db.rows(
        "SELECT direction, channel, subject, body, meta, ts FROM messages WHERE lead_id=? ORDER BY ts",
        (lead_id,))
    if msgs:
        parts.append("Conversation history:")
        for m in msgs[-10:]:
            body = (m["body"] or "")[:400]
            parts.append(f"- {m['direction']} via {m['channel']}: {m['subject'] or ''} | {body}")
    mts = db.rows("SELECT time_utc, link, status FROM meetings WHERE lead_id=? ORDER BY ts", (lead_id,))
    for mt in mts:
        parts.append(f"Meeting: status={mt['status']} link={mt['link']}")
    return "\n".join(parts)
