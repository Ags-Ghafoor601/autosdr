"""Dev: end-to-end approval-mode test: queue draft → approve via API → live send."""
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from app import db  # noqa: E402
from app.tools import emailer  # noqa: E402

db.kv_set("approval_mode", True)
lead = db.one("SELECT * FROM leads WHERE stage='contacted' LIMIT 1")
r = emailer.send_or_queue(
    "i243013@isb.nu.edu.pk", "Approval-mode test email",
    "This email was queued as a draft, then approved by a human, then sent live.",
    lead_id=lead["id"], contact_id=None, meta={"kind": "approval_test"})
print("QUEUED:", r)
assert r["status"] == "draft"

base = "http://localhost:8000"
ob = httpx.get(f"{base}/api/outbox", timeout=15).json()
print("OUTBOX size:", len(ob["drafts"]))
assert any(d["id"] == r["id"] for d in ob["drafts"])

ap = httpx.post(f"{base}/api/outbox/{r['id']}/approve", timeout=60).json()
print("APPROVED →", ap)
assert ap["ok"] and ap["channel"] == "email"

db.kv_set("approval_mode", False)
print("approval mode restored to OFF — PASS")
