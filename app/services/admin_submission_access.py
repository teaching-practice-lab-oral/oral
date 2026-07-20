"""Shared authorization and hydration for admin submission workflows."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db_helpers import get_assignment_or_404
from app.models import Assignment, Submission, User
from app.services.admin_scope import (
    ensure_admin_can_access_assignment,
    ensure_admin_can_access_student_assignment,
)
from app.services.grading import grade_admin_payload, latest_grade
from app.services.submission_data import hydrate_submission_from_normalized


def get_accessible_assignment(db: Session, admin: User, assignment_id: int) -> Assignment:
    assignment = get_assignment_or_404(db, assignment_id)
    ensure_admin_can_access_assignment(admin, assignment)
    return assignment


def get_accessible_submission_context(
    db: Session,
    admin: User,
    submission_id: int,
    *,
    lock: bool = False,
    hydrate: bool = True,
) -> tuple[Submission, User, Assignment]:
    query = db.query(Submission).filter(Submission.id == submission_id)
    if lock:
        query = query.with_for_update()
    submission = query.first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if hydrate:
        hydrate_submission_from_normalized(db, submission)
        grade = latest_grade(db, submission.id)
        setattr(submission, "latest_grade_data", grade_admin_payload(grade) if grade else None)
    student = db.query(User).filter(User.id == submission.user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    assignment = get_accessible_assignment(db, admin, submission.assignment_id)
    ensure_admin_can_access_student_assignment(admin, student, assignment)
    return submission, student, assignment
