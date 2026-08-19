"""Meetings: per-email booking links (extra credit: NEW link per outreach email),
slot picking on an in-app booking page, and real Jitsi video-call links.
"""
import secrets
from datetime import datetime, timedelta, timezone

from .. import bus, db
from ..config import BOOKING_BASE_URL


def booking_link(lead_id: str, contact_id: str | None) -> str:
    """Generate a fresh booking token+link for this outreach email."""
    token = secrets.token_urlsafe(8)
    db.kv_set(f"booking:{token}", {"lead_id": lead_id, "contact_id": contact_id,
                                   "created": db.now()})
    link = f"{BOOKING_BASE_URL}/book/{token}"
    bus.emit("meeting", "step", f"new booking link generated: {link}", lead_id=lead_id)
    return link


def slots(days: int = 5) -> list[dict]:
    """Next business-day slots, 10:00-16:00 PKT, hourly."""
    out = []
    now = datetime.now(timezone.utc)
    d = now
    while len(out) < days * 4:
        d += timedelta(days=1)
        if d.weekday() >= 5:
            continue
        for hour_pkt in (10, 12, 14, 16):
            t = d.replace(hour=hour_pkt - 5, minute=0, second=0, microsecond=0)  # PKT=UTC+5
            out.append({"utc": t.timestamp(),
                        "label": t.astimezone(timezone(timedelta(hours=5))).strftime("%a %d %b, %I:%M %p PKT")})
    return out[:days * 4]


def meeting_link(lead_name: str) -> str:
    slug = "".join(ch for ch in lead_name.title() if ch.isalnum())[:20]
    return f"https://meet.jit.si/AutoSDR-{slug}-{secrets.token_hex(3)}"


def finalize(token: str, slot_utc: float) -> dict | None:
    info = db.kv_get(f"booking:{token}")
    if not info:
        return None
    lead = db.one("SELECT * FROM leads WHERE id=?", (info["lead_id"],))
    link = meeting_link(lead["name"])
    mid = db.insert("meetings", {
        "lead_id": info["lead_id"], "contact_id": info.get("contact_id"),
        "time_utc": slot_utc, "link": link, "status": "scheduled",
        "briefing": None, "ts": db.now(),
    })
    label = datetime.fromtimestamp(slot_utc, timezone(timedelta(hours=5))).strftime(
        "%A %d %B %Y, %I:%M %p PKT")
    bus.emit("meeting", "decision",
             f"meeting finalized with {lead['name']}: {label} · {link}",
             {"meeting_id": mid}, lead_id=info["lead_id"])
    return {"meeting_id": mid, "lead_id": info["lead_id"], "contact_id": info.get("contact_id"),
            "time_utc": slot_utc, "time_label": label, "link": link}
