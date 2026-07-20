"""Durable lifecycle governance for private objects owned by submissions."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ObjectDeletionTask, Submission, User
from app.utils import taipei_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubmissionAssetRef:
    student_id: str
    submission_id: int


def list_submission_asset_refs(
    db: Session,
    *,
    assignment_id: int | None = None,
    user_id: int | None = None,
    user_ids: list[int] | None = None,
) -> list[SubmissionAssetRef]:
    query = db.query(User.student_id, Submission.id).join(Submission, Submission.user_id == User.id)
    if assignment_id is not None:
        query = query.filter(Submission.assignment_id == assignment_id)
    if user_id is not None:
        query = query.filter(Submission.user_id == user_id)
    if user_ids is not None:
        query = query.filter(Submission.user_id.in_(user_ids) if user_ids else False)
    return [SubmissionAssetRef(student_id=row[0], submission_id=row[1]) for row in query.all()]


def _prefixes(refs: list[SubmissionAssetRef]) -> list[str]:
    return [
        prefix
        for ref in refs
        for prefix in (
            f"audio/{ref.student_id}/{ref.submission_id}/",
            f"reflection/{ref.student_id}/{ref.submission_id}/",
        )
    ]


def _enqueue_targets(db: Session, target_type: str, targets: list[str]) -> int:
    clean_targets = sorted({target for target in targets if target})
    if not clean_targets:
        return 0
    existing = {
        row[0]
        for row in db.query(ObjectDeletionTask.target)
        .filter(
            ObjectDeletionTask.target_type == target_type,
            ObjectDeletionTask.target.in_(clean_targets),
        )
        .all()
    }
    for target in clean_targets:
        if target not in existing:
            db.add(ObjectDeletionTask(target_type=target_type, target=target))
    return len(clean_targets) - len(existing)


def enqueue_object_cleanup(db: Session, keys: list[str]) -> int:
    """Queue exact objects in the caller's transaction."""
    return _enqueue_targets(db, "key", keys)


def enqueue_submission_asset_cleanup(db: Session, refs: list[SubmissionAssetRef]) -> int:
    return _enqueue_targets(db, "prefix", _prefixes(refs))


async def delete_uncommitted_object(key: str | None) -> None:
    """Compensate an upload rejected before it became a durable DB reference.

    Immediate cleanup is preferred; a failed cleanup is converted to a durable
    exact-key deletion task using its own short transaction.
    """
    if not key:
        return
    from app.services import storage

    try:
        await storage.delete_file_async(key)
        return
    except Exception:
        logger.warning("immediate cleanup failed for uncommitted object %s", key, exc_info=True)
    try:
        with SessionLocal() as db:
            enqueue_object_cleanup(db, [key])
            db.commit()
    except Exception:
        logger.exception("could not enqueue cleanup for uncommitted object %s", key)


def process_object_deletion_queue(*, limit: int = 100) -> dict[str, int]:
    """Run pending exact-key/prefix deletions; failures remain queued."""
    from app.services import storage

    now = taipei_now()
    counts = {"completed": 0, "failed": 0, "objects": 0}
    with SessionLocal() as db:
        tasks = (
            db.query(ObjectDeletionTask)
            .filter(
                ObjectDeletionTask.completed_at.is_(None),
                ObjectDeletionTask.next_attempt_at <= now,
            )
            .order_by(ObjectDeletionTask.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .all()
        )
        for task in tasks:
            try:
                if task.target_type == "key":
                    storage.delete_file(task.target)
                    object_count = 1
                else:
                    keys = storage.list_objects_with_prefix(task.target)
                    for key in keys:
                        storage.delete_file(key)
                    object_count = len(keys)
                task.completed_at = taipei_now()
                task.last_error = None
                counts["completed"] += 1
                counts["objects"] += object_count
            except Exception as exc:
                task.attempts += 1
                delay_minutes = min(24 * 60, 2 ** min(task.attempts, 10))
                task.next_attempt_at = taipei_now() + timedelta(minutes=delay_minutes)
                task.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                counts["failed"] += 1
                logger.exception(
                    "object deletion failed for %s %s",
                    task.target_type,
                    task.target,
                )
        db.commit()
    return counts


async def process_object_deletion_queue_async() -> dict[str, int]:
    return await asyncio.to_thread(process_object_deletion_queue)
