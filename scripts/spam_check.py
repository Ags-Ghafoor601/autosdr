"""Dev: look for allowlisted-sender mail in Gmail Spam."""
import imaplib
import email as email_lib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from app.config import EMAIL_ALLOWLIST, IMAP_HOST, SMTP_APP_PASSWORD, SMTP_USER  # noqa: E402

M = imaplib.IMAP4_SSL(IMAP_HOST)
M.login(SMTP_USER, SMTP_APP_PASSWORD)
for box in ('"[Gmail]/Spam"', "INBOX"):
    st, _ = M.select(box, readonly=True)
    if st != "OK":
        continue
    for sender in EMAIL_ALLOWLIST:
        _, data = M.search(None, "FROM", f'"{sender}"')
        ids = data[0].split() if data and data[0] else []
        print(f"{box}: {len(ids)} messages from {sender}")
        for num in ids[-3:]:
            _, md = M.fetch(num, "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])")
            hdr = email_lib.message_from_bytes(md[0][1])
            print("   ", (hdr.get("Date") or "")[:31], "|", (hdr.get("Subject") or "")[:70])
M.logout()
