"""Authenticated downloads of a student's own complete result package."""

import tempfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from app.auth import get_current_student
from app.database import get_db
from app.models import Assignment, User
from app.services.grading import latest_grade
from app.services import rate_limiter
from app.services.export_lock import acquire_student_export_lease
from app.services.result_delivery import (
    result_package_filename,
    write_graded_submission_result_package,
)
from ._common import get_own_submission


router = APIRouter(prefix="/api/student", tags=["student-exports"])


async def _stream_and_close(file_object, chunk_size: int = 64 * 1024):
    try:
        while True:
            chunk = file_object.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        file_object.close()


async def _close_file(file_object) -> None:
    file_object.close()


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

    rate_limiter.reserve_costly_action(
        current_user.id,
        rate_limiter.CostlyAction.STUDENT_RESULT_EXPORT,
        resource_id=submission.id,
    )
    lease = acquire_student_export_lease(submission.id)
    output = None
    try:
        output = tempfile.TemporaryFile(mode="w+b")
        try:
            content_length = write_graded_submission_result_package(
                output,
                db,
                current_user,
                assignment,
                submission,
                grade,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        if output is not None:
            output.close()
        raise
    finally:
        lease.release()

    filename = result_package_filename(current_user, assignment, submission)
    return StreamingResponse(
        _stream_and_close(output),
        media_type="application/zip",
        # Starlette may cancel its threadpool iterator on client disconnect
        # without closing the underlying synchronous generator.  The response
        # background callback is a second, idempotent cleanup boundary.
        background=BackgroundTask(_close_file, output),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
            "Content-Length": str(content_length),
            "X-Content-Type-Options": "nosniff",
        },
    )
