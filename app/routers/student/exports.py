"""Authenticated download of a student's own graded learning report (Word only)."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import get_current_student
from app.database import get_db
from app.db_helpers import get_latest_submission
from app.models import Assignment, User
from app.services.grading import latest_grade
from app.services import rate_limiter
from app.services.export_lock import acquire_student_export_lease
from app.services.result_delivery import (
    build_graded_submission_report,
    result_report_filename,
)
from ._common import get_own_submission


router = APIRouter(prefix="/api/student", tags=["student-exports"])

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/submissions/{submission_id}/export-result-package")
def export_result_package(
    submission_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_own_submission(db, submission_id, current_user.id)
    if submission.submitted_at is None:
        raise HTTPException(status_code=409, detail="作業尚未完成，無法匯出")
    latest = get_latest_submission(
        db,
        current_user.id,
        submission.assignment_id,
        submitted_only=True,
    )
    if latest is None or latest.id != submission.id:
        raise HTTPException(status_code=409, detail="只能匯出最新一次完成的作業")

    assignment = db.get(Assignment, submission.assignment_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="找不到這份作業")
    grade = latest_grade(db, submission.id)
    if grade is None:
        raise HTTPException(status_code=409, detail="老師還沒批改完，暫時無法匯出")

    rate_limiter.reserve_costly_action(
        current_user.id,
        rate_limiter.CostlyAction.STUDENT_RESULT_EXPORT,
        resource_id=submission.id,
    )
    lease = acquire_student_export_lease(submission.id)
    try:
        try:
            document = build_graded_submission_report(
                db,
                current_user,
                assignment,
                submission,
                grade,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        lease.release()

    filename = result_report_filename(current_user, assignment, submission)
    return Response(
        content=document,
        media_type=DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
