"""Dev inspector: dump the state of contacted/interested leads.
Run from repo root: .venv/Scripts/python scripts/inspect_state.py [--full]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db  # noqa: E402

for lead in db.rows("SELECT * FROM leads WHERE stage NOT IN ('discovered','potential') ORDER BY updated_ts"):
    print(f"\n=== {lead['name']} [{lead['stage']}] score={lead['score']} ===")
    if lead["service"]:
        svc = json.loads(lead["service"])
        print(f"  SERVICE: {svc.get('service_name')} — {(svc.get('why') or '')[:110]}")
    for c in db.rows("SELECT name,role,email,email_status FROM contacts WHERE lead_id=?", (lead["id"],)):
        print(f"  CONTACT: {c['name']} | {c['role']} | {c['email']} [{c['email_status']}]")
    for m in db.rows("SELECT direction,channel,subject,body,ts FROM messages WHERE lead_id=? ORDER BY ts", (lead["id"],)):
        print(f"  MSG {m['direction']} [{m['channel']}]: {(m['subject'] or '')[:70]}")
        if "--full" in sys.argv:
            print("    " + (m["body"] or "").replace("\n", "\n    ")[:1500])
    for f in db.rows("SELECT kind,status,due_ts FROM followups WHERE lead_id=?", (lead["id"],)):
        print(f"  FOLLOWUP: {f['kind']} [{f['status']}] due={f['due_ts'] - db.now():+.0f}s")
    for mt in db.rows("SELECT time_utc,link,status FROM meetings WHERE lead_id=?", (lead["id"],)):
        print(f"  MEETING: {mt['status']} {mt['link']}")
