"""Orchestrator: drives each lead through the full pipeline.

Discovered -> Potential -> Researching -> Qualified -> Contacted -> ...
Runs as a background thread; every step is a bus event; a stop flag lets the
operator halt between leads. Failures on one lead never kill the run.
"""
import threading

from . import bus, db, memory

_run_lock = threading.Lock()
_stop = threading.Event()
_running = False


def running() -> bool:
    return _running


def stop():
    _stop.set()
    bus.emit("orchestrator", "step", "stop requested — finishing current lead")


def run_pipeline(max_leads: int = 5, threshold: int = 60, sender_name: str = "Tehseen"):
    """Full autonomous run: discovery, then research→qualify→match→people→outreach per lead."""
    global _running
    if not _run_lock.acquire(blocking=False):
        bus.emit("orchestrator", "error", "a pipeline run is already active")
        return
    _running = True
    _stop.clear()
    try:
        from .agents import discovery, outreach, people, qualify, research, service_match
        bus.emit("orchestrator", "plan",
                 f"AUTONOMOUS RUN: discover → cheap-filter → for up to {max_leads} leads: "
                 f"deep research → qualify (≥{threshold}%) → service match → decision makers → outreach")
        icp = db.kv_get("icp")
        if not (db.kv_get("company_profile") and icp):
            bus.emit("orchestrator", "error", "setup incomplete: need company profile + ICP")
            return
        stats = discovery.run()
        bus.emit("orchestrator", "step",
                 f"discovery: {stats['kept']} potential leads (dropped {stats['dropped']})")
        leads = db.rows("SELECT id, name FROM leads WHERE stage='potential' "
                        "ORDER BY created_ts LIMIT ?", (max_leads,))
        done = 0
        for l in leads:
            if _stop.is_set():
                bus.emit("orchestrator", "step", "run stopped by operator")
                break
            try:
                research.run_one(l["id"])
                verdict = qualify.run_one(l["id"], threshold)
                if verdict["qualified"]:
                    service_match.run_one(l["id"])
                    contacts = people.run_one(l["id"])
                    if contacts:
                        outreach.run_one(l["id"], sender_name)
                done += 1
            except Exception as e:  # noqa: BLE001
                bus.emit("orchestrator", "error", f"lead {l['name']} failed: {str(e)[:150]}",
                         lead_id=l["id"])
        q = db.one("SELECT COUNT(*) n FROM leads WHERE stage IN "
                   "('contacted','interested','meeting_scheduled')")["n"]
        bus.emit("orchestrator", "decision",
                 f"run complete: {done} leads processed, {q} in active outreach. "
                 f"Follow-ups and inbox now run autonomously.")
        memory.remember(None, "run", f"Pipeline run: {done} leads processed, {q} contacted")
    finally:
        _running = False
        _run_lock.release()


def advance_one(lead_id: str, sender_name: str = "Tehseen"):
    """Drive a single lead through its next steps (research→…→outreach). For per-lead control."""
    from .agents import outreach, people, qualify, research, service_match
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    assert lead, "no such lead"
    try:
        if lead["stage"] in ("discovered", "potential"):
            research.run_one(lead_id)
            v = qualify.run_one(lead_id)
            if not v["qualified"]:
                return
            service_match.run_one(lead_id)
            if people.run_one(lead_id):
                outreach.run_one(lead_id, sender_name)
        elif lead["stage"] == "qualified":
            service_match.run_one(lead_id)
            if people.run_one(lead_id):
                outreach.run_one(lead_id, sender_name)
    except Exception as e:  # noqa: BLE001
        bus.emit("orchestrator", "error", f"advance failed: {str(e)[:150]}", lead_id=lead_id)


def start_run_async(max_leads: int = 5, threshold: int = 60, sender_name: str = "Tehseen"):
    t = threading.Thread(target=run_pipeline, args=(max_leads, threshold, sender_name),
                         daemon=True)
    t.start()
    return t
