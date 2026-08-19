"""Email transport: live SMTP/IMAP (Gmail) or simulated inbox. One hard rule:

    LIVE SENDS ONLY GO TO ALLOWLISTED ADDRESSES.

Anything else silently routes to the simulated channel and is labeled so in the
UI. Researching real companies is fine; cold-emailing real strangers from a
hackathon demo is not. The README documents this.
"""
import imaplib
import os
import smtplib
import email as email_lib
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .. import bus, db
from ..config import (EMAIL_MODE, EMAIL_ALLOWLIST, IMAP_HOST, SMTP_APP_PASSWORD,
                      SMTP_HOST, SMTP_PORT, SMTP_USER)

DEMO_REDIRECT = os.getenv("EMAIL_DEMO_REDIRECT", "").lower().strip()


def send(to_addr: str, subject: str, body: str, *, lead_id: str | None,
         contact_id: str | None, meta: dict | None = None) -> dict:
    """Send (or simulate) an email; always persisted to messages (long-term memory)."""
    meta = dict(meta or {})
    to_addr = to_addr.lower().strip()
    # Demo redirect: deliver prospect-bound mail to our sandbox inbox instead of
    # the real company. Intended recipient is recorded and displayed.
    if (EMAIL_MODE == "live" and DEMO_REDIRECT and to_addr not in EMAIL_ALLOWLIST):
        meta["intended_to"] = to_addr
        bus.emit("outreach", "step",
                 f"demo redirect: intended {to_addr} → delivered to sandbox inbox {DEMO_REDIRECT}",
                 lead_id=lead_id)
        to_addr = DEMO_REDIRECT
    live_ok = (EMAIL_MODE == "live" and SMTP_USER and SMTP_APP_PASSWORD
               and to_addr in EMAIL_ALLOWLIST)
    channel = "email" if live_ok else "email_sim"
    status = "sent"
    if EMAIL_MODE == "live" and not live_ok and to_addr not in EMAIL_ALLOWLIST:
        bus.emit("outreach", "step",
                 f"allowlist guard: {to_addr} not allowlisted → simulated send", lead_id=lead_id)
    if live_ok:
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = SMTP_USER
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_APP_PASSWORD)
                s.sendmail(SMTP_USER, [to_addr], msg.as_string())
        except Exception as e:  # noqa: BLE001
            channel, status = "email_sim", f"live send failed: {str(e)[:120]} — stored as simulated"
            bus.emit("outreach", "error", f"SMTP failed → simulated: {str(e)[:140]}", lead_id=lead_id)
    mid = db.insert("messages", {
        "lead_id": lead_id, "contact_id": contact_id, "direction": "out",
        "channel": channel, "subject": subject, "body": body,
        "meta": _json(meta or {}), "status": status, "ts": db.now(),
    })
    bus.emit("outreach", "email",
             f"{'LIVE' if channel=='email' else 'SIM'} email → {to_addr}: {subject[:70]}",
             {"message_id": mid, "to": to_addr}, lead_id=lead_id)
    return {"id": mid, "channel": channel, "status": status}


def send_or_queue(to_addr: str, subject: str, body: str, *, lead_id: str | None,
                  contact_id: str | None, meta: dict | None = None) -> dict:
    """Approval-mode aware send: when the human-review toggle is ON, outreach is
    queued as a draft for one-click approval instead of sending immediately."""
    if db.kv_get("approval_mode", False):
        meta = dict(meta or {})
        meta["to_addr"] = to_addr.lower().strip()
        mid = db.insert("messages", {
            "lead_id": lead_id, "contact_id": contact_id, "direction": "out",
            "channel": "email", "subject": subject, "body": body,
            "meta": _json(meta), "status": "draft", "ts": db.now(),
        })
        bus.emit("outreach", "step",
                 f"draft queued for human approval → {to_addr}: {subject[:60]}",
                 {"message_id": mid}, lead_id=lead_id)
        return {"id": mid, "channel": "email_draft", "status": "draft"}
    return send(to_addr, subject, body, lead_id=lead_id, contact_id=contact_id, meta=meta)


def poll_replies(agent: str = "inbox") -> list[dict]:
    """Fetch unseen IMAP messages from allowlisted senders; store as direction=in."""
    if EMAIL_MODE != "live" or not (SMTP_USER and SMTP_APP_PASSWORD):
        return []
    out = []
    try:
        M = imaplib.IMAP4_SSL(IMAP_HOST)
        M.login(SMTP_USER, SMTP_APP_PASSWORD)
        M.select("INBOX")
        # Search per allowlisted sender — an inbox with 20k unread mails must never
        # be scanned wholesale on a 20s tick.
        nums = []
        for sender in EMAIL_ALLOWLIST:
            _, data = M.search(None, "UNSEEN", "FROM", f'"{sender}"')
            if data and data[0]:
                nums += data[0].split()
        for num in nums[-10:]:
            _, msg_data = M.fetch(num, "(RFC822)")  # marks \Seen — ours only
            raw = email_lib.message_from_bytes(msg_data[0][1])
            from_addr = email_lib.utils.parseaddr(raw.get("From", ""))[1].lower()
            if EMAIL_ALLOWLIST and from_addr not in EMAIL_ALLOWLIST:
                continue
            subject = _decode(raw.get("Subject", ""))
            body = _body_text(raw)[:4000]
            out.append({"from": from_addr, "subject": subject, "body": body})
            bus.emit(agent, "tool_result", f"reply received from {from_addr}: {subject[:60]}")
        M.logout()
    except Exception as e:  # noqa: BLE001
        bus.emit(agent, "error", f"IMAP poll failed: {str(e)[:140]}")
    return out


def _decode(s: str) -> str:
    parts = decode_header(s)
    return "".join(p.decode(enc or "utf-8", "ignore") if isinstance(p, bytes) else p
                   for p, enc in parts)


def _body_text(raw) -> str:
    if raw.is_multipart():
        for part in raw.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode("utf-8", "ignore")
        for part in raw.walk():
            if part.get_content_type() == "text/html":
                from bs4 import BeautifulSoup
                return BeautifulSoup(part.get_payload(decode=True).decode("utf-8", "ignore"),
                                     "html.parser").get_text(" ", strip=True)
        return ""
    return raw.get_payload(decode=True).decode("utf-8", "ignore")


def _json(o) -> str:
    import json
    return json.dumps(o, ensure_ascii=False)
