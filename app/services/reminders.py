"""Assignment deadline reminders.

Finds assignments whose ``due_date`` falls within the next ``WINDOW_HOURS`` and emails
every student in the assignment's class(es) who has not yet completed it. A row in
``assignment_reminders`` (UNIQUE assignment_id+user_id) guarantees each student is
reminded at most once per assignment, so re-running the scan is always safe.
"""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Assignment, User, Submission, AssignmentReminder
from app.services import mail
from app.utils import taipei_now

logger = logging.getLogger(__name__)

WINDOW_HOURS = 72
_PACE = 0.4               # seconds between sends, eases Outlook rate limits
_ADVISORY_LOCK_KEY = 845_127_001  # arbitrary fixed key for the reminder scheduler

def find_due_soon_targets(db: Session, now=None) -> list[dict]:
    """Return reminder target details, including both student mailboxes, for
    every student who should be reminded right now (no email is sent here)."""
    now = now or taipei_now()
    horizon = now + timedelta(hours=WINDOW_HOURS)

    assignments = (
        db.query(Assignment)
        .filter(
            Assignment.is_active.is_(True),
            Assignment.due_date.isnot(None),
            Assignment.due_date > now,
            Assignment.due_date <= horizon,
        )
        .all()
    )

    targets: list[dict] = []
    for a in assignments:
        # Students this assignment applies to: NULL course_nums = everyone, else by class.
        q = db.query(User).filter(User.role == "student", User.is_active.is_(True))
        if a.course_nums:
            q = q.filter(User.course_num.in_(a.course_nums))
        students = q.all()
        if not students:
            continue

        # Who already completed it (any submitted attempt) — skip them.
        completed_ids = {
            uid for (uid,) in db.query(Submission.user_id)
            .filter(Submission.assignment_id == a.id, Submission.submitted_at.isnot(None))
            .distinct()
        }
        # Who was already reminded for this assignment — skip them.
        reminded_ids = {
            uid for (uid,) in db.query(AssignmentReminder.user_id)
            .filter(AssignmentReminder.assignment_id == a.id)
        }

        hours_left = max(0, int((a.due_date - now).total_seconds() // 3600))
        for u in students:
            if u.id in completed_ids or u.id in reminded_ids or not u.email:
                continue
            if u.email.strip().casefold() in settings.reminder_excluded_emails_set:
                continue
            targets.append({
                "assignment_id": a.id,
                "user_id": u.id,
                "email": u.email,
                "backup_email": u.backup_email,
                "name": u.name,
                "title": a.title,
                "due_date": a.due_date,
                "hours_left": hours_left,
            })
    return targets


async def deliver_reminders(targets: list[dict]) -> dict:
    """Send reminder emails for the given targets, claiming each in the dedup table
    first so concurrent runs can't double-send; a failed send releases its claim so it
    retries on the next pass. Uses its own DB session (safe for background tasks)."""
    sent = 0
    failed = 0
    db = SessionLocal()
    try:
        for t in targets:
            # Claim — if another run already inserted this (assignment,user), skip.
            claim = AssignmentReminder(assignment_id=t["assignment_id"], user_id=t["user_id"])
            db.add(claim)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                continue

            try:
                await mail.send_assignment_reminder_email(
                    t["email"], t["name"], t["title"], t["due_date"], t.get("hours_left"),
                    t.get("backup_email"),
                )
                sent += 1
                await asyncio.sleep(_PACE)
            except Exception:
                logger.exception(
                    "Failed to send reminder for assignment %s to %s",
                    t["assignment_id"], t["email"],
                )
                # Release the claim so it is retried next run.
                db.delete(claim)
                db.commit()
                failed += 1
        if sent or failed:
            logger.info("assignment reminders: %d sent, %d failed", sent, failed)
        return {"targets": len(targets), "sent": sent, "failed": failed}
    finally:
        db.close()


async def run_due_soon_reminders(now=None) -> dict:
    """Scan + deliver in one call (used by both the scheduler and the manual trigger)."""
    with SessionLocal() as db:
        targets = find_due_soon_targets(db, now)
    return await deliver_reminders(targets)


async def reminder_scheduler_loop(interval_seconds: int = 3600) -> None:
    """Background loop: every hour, one worker (whoever wins the advisory lock) runs the
    scan. The lock keeps the other gunicorn workers from doing duplicate work."""
    # Stagger startup a little so all workers don't hit the lock at the same instant.
    await asyncio.sleep(15)
    while True:
        try:
            with SessionLocal() as db:
                got_lock = db.execute(
                    text("SELECT pg_try_advisory_lock(:k)"), {"k": _ADVISORY_LOCK_KEY}
                ).scalar()
                if got_lock:
                    try:
                        targets = find_due_soon_targets(db)
                    finally:
                        db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _ADVISORY_LOCK_KEY})
                        db.commit()
                    if targets:
                        await deliver_reminders(targets)
        except Exception:
            logger.exception("reminder scheduler tick failed")
        await asyncio.sleep(interval_seconds)
