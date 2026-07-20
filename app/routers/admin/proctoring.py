"""Admin read access to per-submission practice integrity events."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_admin
from app.database import get_db
from app.models import Assignment, Submission, SubmissionProctorEvent, User
from app.services.admin_scope import ensure_admin_can_access_student_assignment


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/submissions/{submission_id}/proctor-events")
def list_proctor_events(
    submission_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="找不到提交紀錄。")
    student = db.query(User).filter(User.id == sub.user_id).first()
    assignment = db.query(Assignment).filter(Assignment.id == sub.assignment_id).first()
    if not student or not assignment:
        raise HTTPException(status_code=404, detail="找不到學生或作業。")
    ensure_admin_can_access_student_assignment(admin, student, assignment)
    rows = (
        db.query(SubmissionProctorEvent)
        .filter(SubmissionProctorEvent.submission_id == sub.id)
        .order_by(SubmissionProctorEvent.created_at.asc(), SubmissionProctorEvent.id.asc())
        .all()
    )
    return {
        "practice_started_at": sub.practice_started_at,
        "practice_deadline_at": sub.practice_deadline_at,
        "events": [
            {
                "id": row.id,
                "event_type": row.event_type,
                "page_path": row.page_path,
                "details": row.details,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }
