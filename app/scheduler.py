"""Background automation: due follow-ups, meeting reminders, IMAP reply polling.

This is what makes the system autonomous rather than click-driven — it acts
on time and on incoming replies with no human in the loop.
"""
from apscheduler.schedulers.background import BackgroundScheduler

from . import bus, db

_sched: BackgroundScheduler | None = None


def _tick_followups():
    due = db.rows("SELECT * FROM followups WHERE status='scheduled' AND due_ts<=?", (db.now(),))
    for f in due:
        try:
            if f["kind"] == "no_reply_followup":
                from .agents import followup
                followup.run_due(f)
            elif f["kind"] == "meeting_reminder":
                from .agents import meeting
                meeting.send_reminder(f)
            elif f["kind"] == "not_now_checkin":
                db.update("followups", f["id"], {"status": "done"})
                bus.emit("followup", "step", "'not now' check-in window reached",
                         lead_id=f["lead_id"])
        except Exception as e:  # noqa: BLE001
            db.update("followups", f["id"], {"status": f"error: {str(e)[:100]}"})
            bus.emit("followup", "error", f"followup {f['kind']} failed: {str(e)[:140]}",
                     lead_id=f["lead_id"])


def _tick_inbox():
    from .tools import emailer
    from .agents import inbox
    for r in emailer.poll_replies():
        try:
            inbox.handle_reply(r["from"], r["subject"], r["body"])
        except Exception as e:  # noqa: BLE001
            bus.emit("inbox", "error", f"reply handling failed: {str(e)[:140]}")


def start():
    global _sched
    if _sched:
        return
    _sched = BackgroundScheduler(daemon=True)
    _sched.add_job(_tick_followups, "interval", seconds=5, max_instances=1, coalesce=True)
    _sched.add_job(_tick_inbox, "interval", seconds=20, max_instances=1, coalesce=True)
    _sched.start()
    bus.emit("system", "step", "scheduler online: follow-ups every 5s, inbox poll every 20s")
