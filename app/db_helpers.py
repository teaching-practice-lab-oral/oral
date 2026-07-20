import json
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Assignment, Submission, User

logger = logging.getLogger(__name__)

def get_assignment_or_404(db: Session, assignment_id: int) -> Assignment:
    a = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return a


def get_latest_submission(
    db: Session,
    user_id: int,
    assignment_id: int,
    submitted_only: bool = False,
) -> Submission | None:
    q = db.query(Submission).filter(
        Submission.user_id == user_id,
        Submission.assignment_id == assignment_id,
    )
    if submitted_only:
        q = q.filter(Submission.submitted_at.isnot(None))
    return q.order_by(Submission.attempt_number.desc()).first()


def advance_submission_stage(sub: Submission, target_stage: int) -> None:
    """Advance submission stage only if not already past target_stage."""
    if sub.stage < target_stage:
        sub.stage = target_stage


def ensure_not_submitted(sub: Submission) -> None:
    """Raise HTTP 400 if the submission has already been finalized."""
    if sub.submitted_at:
        raise HTTPException(status_code=400, detail="Submission already completed")


def get_submission_or_403(db: Session, submission_id: int, user_id: int) -> "Submission":
    from app.models import Submission as _Sub
    sub = db.query(_Sub).filter(_Sub.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return sub


def get_submission_locked_or_403(db: Session, submission_id: int, user_id: int) -> "Submission":
    from app.models import Submission as _Sub
    sub = db.query(_Sub).filter(_Sub.id == submission_id).with_for_update().first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return sub


def load_users_by_ids(db: Session, ids) -> dict[int, User]:
    """Batch-load users into an {id: User} map (skips falsy ids); returns {} if none."""
    unique = list({i for i in ids if i})
    if not unique:
        return {}
    return {u.id: u for u in db.query(User).filter(User.id.in_(unique)).all()}


def safe_json_parse(value) -> dict | list:
    """Safely parse a JSON string or pass-through dict/list; return {} on failure."""
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception as e:
        logger.error("Failed to parse JSON field: %s", e)
        return {}
