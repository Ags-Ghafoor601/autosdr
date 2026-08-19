"""Dev: last N events + advanced leads + costs. Run: .venv/Scripts/python scripts/recent.py [N]"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 14
now = time.time()
for e in reversed(db.rows("SELECT seq,ts,agent,type,label FROM events ORDER BY seq DESC LIMIT ?", (n,))):
    print(f"{now - e['ts']:>6.0f}s ago | {e['agent']:>12} | {e['type']:<11} | {e['label'][:95]}")
print()
for l in db.rows("SELECT name,stage,score FROM leads WHERE stage NOT IN ('discovered','potential')"):
    print(f"LEAD: {l['name']} | {l['stage']} | {l['score']}")
print("\nCOSTS:", db.kv_get("costs"))
