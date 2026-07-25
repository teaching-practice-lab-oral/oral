"""Authenticated downloads of a student's own complete result package."""

import io
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import get_current_student
from app.database import get_db
from app.models import Assignment, User
from app.services.grading import latest_grade
from app.services.result_delivery import (
    build_graded_submission_result_package,
    result_package_filename,
)
from ._common import get_own_submission


router = APIRouter(prefix="/api/student", tags=["student-exports"])


@router.get("/submissions/{submission_id}/export-result-package")
def export_result_package(
    submission_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_own_submission(db, submission_id, current_user.id)
    if submission.submitted_at is None:
        raise HTTPException(status_code=409, detail="作業尚未完成，無法匯出成果包")

    assignment = db.get(Assignment, submission.assignment_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="找不到這份作業")
    grade = latest_grade(db, submission.id)
    if grade is None:
        raise HTTPException(status_code=409, detail="老師尚未完成批改，暫時無法匯出成果包")

    try:
        payload = build_graded_submission_result_package(
            db,
            current_user,
            assignment,
            submission,
            grade,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    filename = result_package_filename(current_user, assignment, submission)
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
        },
    )
