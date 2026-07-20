"""Student assignment access policy for current work and owned history."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Assignment, Submission, User
from app.services.admin_scope import normalize_course_num, normalize_course_nums
from app.utils import taipei_now


def student_is_in_assignment_scope(assignment: Assignment, student: User) -> bool:
    if not assignment.is_active:
        return False
    course_nums = normalize_course_nums(assignment.course_nums)
    return not course_nums or normalize_course_num(student.course_num) in course_nums


def ensure_student_is_in_assignment_scope(assignment: Assignment, student: User) -> None:
    if not student_is_in_assignment_scope(assignment, student):
        raise HTTPException(status_code=404, detail="Assignment not found or inactive")


def student_can_access_current_assignment(assignment: Assignment, student: User) -> bool:
    if not student_is_in_assignment_scope(assignment, student):
        return False
    start_date = getattr(assignment, "start_date", None)
    return start_date is None or taipei_now() >= start_date


def ensure_student_can_access_current_assignment(assignment: Assignment, student: User) -> None:
    if not student_can_access_current_assignment(assignment, student):
        raise HTTPException(status_code=404, detail="Assignment not found or not yet open")


def student_owns_assignment_history(
    db: Session,
    assignment_id: int,
    user_id: int,
) -> bool:
    return (
        db.query(Submission.id)
        .filter(
            Submission.assignment_id == assignment_id,
            Submission.user_id == user_id,
        )
        .first()
        is not None
    )


def ensure_student_can_read_assignment_history(
    db: Session,
    assignment: Assignment,
    student: User,
) -> None:
    if student_can_access_current_assignment(assignment, student):
        return
    if student_owns_assignment_history(db, assignment.id, student.id):
        return
    raise HTTPException(status_code=404, detail="Assignment not found")


def ensure_student_can_mutate_submission_assignment(
    assignment: Assignment | None,
    student: User | None,
) -> None:
    if assignment is None or student is None or not student_can_access_current_assignment(assignment, student):
        raise HTTPException(status_code=403, detail="這份作業目前未開放，僅可檢視，無法繼續修改。")
