"""Database-backed student online capacity leases.

The app runs multiple gunicorn workers, so "currently online" cannot live in
process memory. StudentPresence keeps one short-lived lease per student and uses
a PostgreSQL advisory transaction lock to make login-time capacity checks
atomic across workers.
"""
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import StudentPresence
from app.utils import taipei_now

_CAPACITY_LOCK_KEY = 845_127_050


def _presence_expiry(now) -> datetime:
    return now + timedelta(seconds=settings.STUDENT_PRESENCE_TTL_SECONDS)


def prune_expired_presence(db: Session, now=None) -> int:
    now = now or taipei_now()
    return (
        db.query(StudentPresence)
        .filter(StudentPresence.expires_at <= now)
        .delete(synchronize_session=False)
    )


def acquire_student_presence(
    db: Session,
    *,
    user_id: int,
    active_session_id: int | None,
    ip_address: str | None,
    device_type: str | None,
    now=None,
) -> None:
    """Create or renew a student's online lease, enforcing the configured cap.

    Call this in the same transaction that creates the ActiveSession. The
    advisory transaction lock serializes the prune/count/insert sequence across
    all workers.
    """
    if settings.STUDENT_ONLINE_LIMIT <= 0:
        return

    now = now or taipei_now()
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CAPACITY_LOCK_KEY})
    prune_expired_presence(db, now)

    current = (
        db.query(StudentPresence)
        .filter(StudentPresence.user_id == user_id)
        .with_for_update()
        .first()
    )
    if current is None:
        online_count = db.query(StudentPresence).filter(StudentPresence.expires_at > now).count()
        if online_count >= settings.STUDENT_ONLINE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="目前同時在線學生已達上限，請稍後再試。",
            )
        current = StudentPresence(user_id=user_id)
        db.add(current)

    current.active_session_id = active_session_id
    current.ip_address = ip_address
    current.device_type = device_type
    current.last_seen_at = now
    current.expires_at = _presence_expiry(now)


def touch_student_presence(
    db: Session,
    *,
    user_id: int,
    active_session_id: int | None,
    ip_address: str | None,
    device_type: str | None,
    now=None,
) -> None:
    now = now or taipei_now()
    lease = db.query(StudentPresence).filter(StudentPresence.user_id == user_id).first()
    if lease is None:
        acquire_student_presence(
            db,
            user_id=user_id,
            active_session_id=active_session_id,
            ip_address=ip_address,
            device_type=device_type,
            now=now,
        )
        return
    lease.active_session_id = active_session_id
    lease.ip_address = ip_address
    lease.device_type = device_type
    lease.last_seen_at = now
    lease.expires_at = _presence_expiry(now)


def release_student_presence(db: Session, *, user_id: int) -> int:
    return (
        db.query(StudentPresence)
        .filter(StudentPresence.user_id == user_id)
        .delete(synchronize_session=False)
    )
