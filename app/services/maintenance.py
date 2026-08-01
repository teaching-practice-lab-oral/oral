"""Low-frequency database cleanup jobs."""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import (
    ActiveSession, AdminAuditLog, ApiUsageLog, CostlyActionUsageLog, LoginEvent, PasswordResetToken,
    ObjectDeletionTask, StudentPresence, SubmissionProctorEvent, WorkerRoutingEvent,
    ResultPackage,
)
from app.utils import taipei_now
from app.services.submission_assets import process_object_deletion_queue

logger = logging.getLogger(__name__)

_ADVISORY_LOCK_KEY = 845_127_002


def _delete_older_than(db: Session, model, column, days: int, now) -> int:
    if days <= 0:
        return 0
    cutoff = now - timedelta(days=days)
    return db.query(model).filter(column < cutoff).delete(synchronize_session=False)


def cleanup_expired_records(db: Session, now=None) -> dict[str, int]:
    now = now or taipei_now()
    counts = {
        "active_sessions": db.query(ActiveSession)
        .filter(ActiveSession.expires_at <= now)
        .delete(synchronize_session=False),
        "student_presence": db.query(StudentPresence)
        .filter(StudentPresence.expires_at <= now)
        .delete(synchronize_session=False),
        "password_reset_tokens": db.query(PasswordResetToken)
        .filter(PasswordResetToken.expires_at <= now)
        .delete(synchronize_session=False),
        "result_packages_expired": db.query(ResultPackage)
        .filter(
            ResultPackage.expires_at.isnot(None),
            ResultPackage.expires_at <= now,
            ResultPackage.state != "expired",
        )
        .update(
            {
                ResultPackage.state: "expired",
                ResultPackage.updated_at: now,
            },
            synchronize_session=False,
        ),
        "login_events": _delete_older_than(
            db,
            LoginEvent,
            LoginEvent.login_at,
            settings.LOGIN_EVENT_RETENTION_DAYS,
            now,
        ),
        "admin_audit_logs": _delete_older_than(
            db,
            AdminAuditLog,
            AdminAuditLog.created_at,
            settings.ADMIN_AUDIT_RETENTION_DAYS,
            now,
        ),
        "api_usage_logs": _delete_older_than(
            db,
            ApiUsageLog,
            ApiUsageLog.called_at,
            settings.API_USAGE_RETENTION_DAYS,
            now,
        ),
        "costly_action_usage_logs": _delete_older_than(
            db,
            CostlyActionUsageLog,
            CostlyActionUsageLog.called_at,
            settings.COSTLY_ACTION_RETENTION_DAYS,
            now,
        ),
        "worker_routing_events": _delete_older_than(
            db,
            WorkerRoutingEvent,
            WorkerRoutingEvent.created_at,
            settings.API_USAGE_RETENTION_DAYS,
            now,
        ),
        "submission_proctor_events": _delete_older_than(
            db,
            SubmissionProctorEvent,
            SubmissionProctorEvent.created_at,
            settings.PROCTOR_EVENT_RETENTION_DAYS,
            now,
        ),
        "completed_object_deletion_tasks": db.query(ObjectDeletionTask)
        .filter(
            ObjectDeletionTask.completed_at.isnot(None),
            ObjectDeletionTask.completed_at < now - timedelta(days=30),
        )
        .delete(synchronize_session=False),
    }
    if any(counts.values()):
        db.commit()
        logger.info("maintenance cleanup pruned rows: %s", counts)
    else:
        db.rollback()
    return counts


async def maintenance_scheduler_loop(interval_seconds: int | None = None) -> None:
    interval = interval_seconds or settings.MAINTENANCE_CLEANUP_INTERVAL_SECONDS
    await asyncio.sleep(30)
    while True:
        try:
            with SessionLocal() as db:
                got_lock = db.execute(
                    text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _ADVISORY_LOCK_KEY}
                ).scalar()
                if got_lock:
                    # cleanup_expired_records commits or rolls back this same
                    # transaction, which releases the xact-scoped lock.  A
                    # session-level lock is unsafe here because commit can
                    # return the connection to the pool before an explicit
                    # unlock runs.
                    cleanup_expired_records(db)
                    process_object_deletion_queue()
        except Exception:
            logger.exception("maintenance cleanup tick failed")
        await asyncio.sleep(interval)
