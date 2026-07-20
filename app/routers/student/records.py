"""Read-only Rubric and formal-grade endpoints for students."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_student
from app.database import get_db
from app.db_helpers import get_assignment_or_404
from app.models import User
from app.services.grading import grade_student_payload, latest_grade, rubric_version_payload
from app.services.student_assignment_access import ensure_student_can_access_current_assignment
from ._common import get_own_submission


router = APIRouter(prefix="/api/student", tags=["student-records"])


@router.get("/assignments/{assignment_id}/rubric")
def get_assignment_rubric(
    assignment_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    assignment = get_assignment_or_404(db, assignment_id)
    ensure_student_can_access_current_assignment(assignment, current_user)
    return rubric_version_payload(assignment.rubric_version)


@router.get("/submissions/{submission_id}/rubric")
def get_submission_rubric(
    submission_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_own_submission(db, submission_id, current_user.id)
    return rubric_version_payload(submission.rubric_version)


@router.get("/submissions/{submission_id}/grade")
def get_latest_submission_grade(
    submission_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_own_submission(db, submission_id, current_user.id)
    row = latest_grade(db, submission.id)
    return {"grade": grade_student_payload(row) if row else None}
