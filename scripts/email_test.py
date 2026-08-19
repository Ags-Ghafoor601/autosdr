"""Dev: verify live SMTP send through the emailer (allowlist + redirect logic included)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from app.tools import emailer  # noqa: E402

r = emailer.send(
    "i243013@isb.nu.edu.pk",
    "AutoSDR live email test",
    "This is AutoSDR's live SMTP test.\n\nIf you can read this, the Gmail app "
    "password works and the live email channel is up.\n\nReply to this email from "
    "this inbox to test the reply-classification loop.\n\n— AutoSDR",
    lead_id=None, contact_id=None, meta={"kind": "smtp_test"},
)
print("RESULT:", r)
