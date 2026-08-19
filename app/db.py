"""SQLite = long-term memory. One connection per call site (check_same_thread off, WAL)."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT, website TEXT,
  location TEXT, industry TEXT, size_hint TEXT, source TEXT,
  stage TEXT NOT NULL DEFAULT 'discovered',
  score INTEGER, score_reasons TEXT, service TEXT, research TEXT,
  created_ts REAL, updated_ts REAL
);
CREATE TABLE IF NOT EXISTS contacts (
  id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, name TEXT, role TEXT,
  email TEXT, email_status TEXT, source TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, kind TEXT, url TEXT,
  quote TEXT, meta TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, lead_id TEXT, contact_id TEXT,
  direction TEXT NOT NULL, channel TEXT NOT NULL,
  subject TEXT, body TEXT, meta TEXT, status TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS meetings (
  id TEXT PRIMARY KEY, lead_id TEXT, contact_id TEXT,
  time_utc REAL, link TEXT, status TEXT, briefing TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS followups (
  id TEXT PRIMARY KEY, lead_id TEXT, due_ts REAL, kind TEXT,
  status TEXT DEFAULT 'scheduled', meta TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, agent TEXT, type TEXT,
  label TEXT, lead_id TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS kb_chunks (
  id TEXT PRIMARY KEY, doc TEXT, idx INTEGER, text TEXT, embedding BLOB
);
CREATE TABLE IF NOT EXISTS memory_notes (
  id TEXT PRIMARY KEY, lead_id TEXT, kind TEXT, note TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""

STAGES = [
    "discovered", "potential", "researching", "qualified", "contacted",
    "interested", "meeting_scheduled", "converted",
    "not_qualified", "not_interested", "do_not_contact",
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_conn = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _connect()
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


@contextmanager
def tx():
    c = conn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> float:
    return time.time()


# ── helpers ──────────────────────────────────────────────────────────────

def insert(table: str, row: dict) -> str:
    row = dict(row)
    row.setdefault("id", new_id())
    keys = ",".join(row)
    ph = ",".join("?" for _ in row)
    with tx() as c:
        c.execute(f"INSERT INTO {table} ({keys}) VALUES ({ph})", list(row.values()))
    return row["id"]


def update(table: str, id_: str, fields: dict):
    sets = ",".join(f"{k}=?" for k in fields)
    with tx() as c:
        c.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*fields.values(), id_])


def rows(sql: str, args: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict | None:
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None


def kv_get(k: str, default=None):
    r = one("SELECT v FROM kv WHERE k=?", (k,))
    return json.loads(r["v"]) if r else default


def kv_set(k: str, v):
    with tx() as c:
        c.execute(
            "INSERT INTO kv (k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, json.dumps(v)),
        )


def set_stage(lead_id: str, stage: str):
    assert stage in STAGES, f"bad stage {stage}"
    update("leads", lead_id, {"stage": stage, "updated_ts": now()})
