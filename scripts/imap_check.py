"""Dev: check IMAP connectivity and list recent inbox senders/subjects."""
import imaplib
import email as email_lib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from app.config import IMAP_HOST, SMTP_APP_PASSWORD, SMTP_USER  # noqa: E402

M = imaplib.IMAP4_SSL(IMAP_HOST)
M.login(SMTP_USER, SMTP_APP_PASSWORD)
M.select("INBOX")
_, data = M.search(None, "ALL")
ids = data[0].split()
print(f"IMAP OK — {len(ids)} messages in INBOX; last 5:")
for num in ids[-5:]:
    _, md = M.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
    hdr = email_lib.message_from_bytes(md[0][1])
    print("  FROM:", (hdr.get("From") or "")[:60], "| SUBJ:", (hdr.get("Subject") or "")[:60])
_, unseen = M.search(None, "UNSEEN")
print("UNSEEN count:", len(unseen[0].split()) if unseen and unseen[0] else 0)
M.logout()
