"""Dev: book the newest booking link of a lead (default: NextStep) through the real API."""
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db  # noqa: E402

name_like = sys.argv[1] if len(sys.argv) > 1 else "NextStep%"
lead = db.one("SELECT id,name FROM leads WHERE name LIKE ?", (name_like,))
assert lead, f"no lead like {name_like}"
best = None
for r in db.rows("SELECT k, v FROM kv WHERE k LIKE 'booking:%'"):
    info = json.loads(r["v"])
    if info["lead_id"] == lead["id"] and (best is None or info["created"] > best[1]):
        best = (r["k"].split(":", 1)[1], info["created"])
assert best, "no booking token for lead"
token = best[0]
print("LEAD:", lead["name"], "TOKEN:", token)

base = "http://localhost:8000"
slots = httpx.get(f"{base}/api/book/{token}", timeout=30).json()
slot = slots["slots"][1]
print("BOOKING SLOT:", slot["label"])
r = httpx.post(f"{base}/api/book/{token}", data={"slot_utc": slot["utc"]}, timeout=180)
print("RESULT:", r.json())
