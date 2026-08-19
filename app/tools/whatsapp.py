"""WhatsApp adapter: greenapi | twilio | callmebot | sim.

Used for: admin meeting alerts (required, brief §13), 30-min pre-meeting
briefing reminders, and optionally messaging the prospect company (extra
credit, allowlist-guarded like email).
"""
import os

import httpx

from .. import bus, db
from ..config import (ADMIN_WHATSAPP, CALLMEBOT_APIKEY, GREENAPI_INSTANCE_ID,
                      GREENAPI_TOKEN, TWILIO_SID, TWILIO_TOKEN, TWILIO_WA_FROM,
                      WHATSAPP_MODE)


def _digits(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def send(to_phone: str, text: str, *, lead_id: str | None = None,
         kind: str = "admin_alert") -> dict:
    mode = WHATSAPP_MODE
    # HARD SAFETY: live WhatsApp only to the admin's own number (or explicit allowlist).
    # Scraped company numbers always route to the simulated channel.
    allowed = {_digits(ADMIN_WHATSAPP)} | {
        _digits(p) for p in os.getenv("WHATSAPP_ALLOWLIST", "").split(",") if p.strip()}
    if _digits(to_phone) not in allowed:
        if mode != "sim":
            bus.emit("whatsapp", "step",
                     f"allowlist guard: {to_phone} not allowlisted → simulated WhatsApp",
                     lead_id=lead_id)
        mode = "sim"
    ok, detail = False, ""
    if mode == "greenapi" and GREENAPI_INSTANCE_ID and GREENAPI_TOKEN:
        ok, detail = _greenapi(to_phone, text)
    elif mode == "twilio" and TWILIO_SID and TWILIO_TOKEN:
        ok, detail = _twilio(to_phone, text)
    elif mode == "callmebot" and CALLMEBOT_APIKEY:
        ok, detail = _callmebot(to_phone, text)
    else:
        mode = "sim"
        ok, detail = True, "simulated"
    channel = "whatsapp" if (ok and mode != "sim") else "whatsapp_sim"
    mid = db.insert("messages", {
        "lead_id": lead_id, "contact_id": None, "direction": "out", "channel": channel,
        "subject": kind, "body": text, "meta": _json({"to": to_phone, "mode": mode,
                                                      "detail": detail[:200]}),
        "status": "sent" if ok else f"failed: {detail[:120]}", "ts": db.now(),
    })
    bus.emit("whatsapp", "whatsapp",
             f"{'LIVE' if channel=='whatsapp' else 'SIM'} WhatsApp → {to_phone} [{kind}]: {text[:80]}",
             {"message_id": mid}, lead_id=lead_id)
    return {"id": mid, "channel": channel, "ok": ok}


def send_admin(text: str, *, lead_id: str | None = None, kind: str = "admin_alert") -> dict:
    return send(ADMIN_WHATSAPP or "+920000000000", text, lead_id=lead_id, kind=kind)


def _greenapi(to_phone: str, text: str):
    try:
        url = (f"https://api.green-api.com/waInstance{GREENAPI_INSTANCE_ID}"
               f"/sendMessage/{GREENAPI_TOKEN}")
        r = httpx.post(url, json={"chatId": f"{_digits(to_phone)}@c.us", "message": text},
                       timeout=20)
        return (r.status_code == 200, r.text[:200])
    except Exception as e:  # noqa: BLE001
        return (False, str(e)[:150])


def _twilio(to_phone: str, text: str):
    try:
        r = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
            data={"From": TWILIO_WA_FROM, "To": f"whatsapp:+{_digits(to_phone)}", "Body": text},
            auth=(TWILIO_SID, TWILIO_TOKEN), timeout=20)
        return (r.status_code in (200, 201), r.text[:200])
    except Exception as e:  # noqa: BLE001
        return (False, str(e)[:150])


def _callmebot(to_phone: str, text: str):
    try:
        r = httpx.get("https://api.callmebot.com/whatsapp.php",
                      params={"phone": _digits(to_phone), "text": text,
                              "apikey": CALLMEBOT_APIKEY}, timeout=25)
        return (r.status_code == 200, r.text[:200])
    except Exception as e:  # noqa: BLE001
        return (False, str(e)[:150])


def _json(o) -> str:
    import json
    return json.dumps(o, ensure_ascii=False)
