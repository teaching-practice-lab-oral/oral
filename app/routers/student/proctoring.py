"""Student-side practice integrity event collection."""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_student
from app.database import get_db
from app.models import SubmissionProctorEvent, User
from app.schemas import ProctorEventCreate
from app.utils import taipei_now
from ._common import get_own_submission


router = APIRouter(prefix="/api/student", tags=["student"])

ALLOWED_EVENT_TYPES = {
    "fullscreen_enter",
    "fullscreen_exit",
    "page_hidden",
    "window_blur",
    "paste_blocked",
    "large_input",
    "time_expired",
}


@router.post("/submissions/{submission_id}/proctor-events", status_code=status.HTTP_204_NO_CONTENT)
def record_proctor_event(
    submission_id: int,
    payload: ProctorEventCreate,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    sub = get_own_submission(db, submission_id, current_user.id)
    if payload.event_type not in ALLOWED_EVENT_TYPES:
        raise HTTPException(status_code=400, detail="不支援的作答事件類型。")
    expected_prefix = f"/student/assignment/{sub.assignment_id}/"
    if not payload.page_path.startswith(expected_prefix):
        raise HTTPException(status_code=400, detail="作答事件頁面不屬於此作業。")
    details = payload.details or None
    if details is not None and len(json.dumps(details, ensure_ascii=False)) > 2000:
        raise HTTPException(status_code=400, detail="作答事件內容過長。")
    db.add(
        SubmissionProctorEvent(
            submission_id=sub.id,
            event_type=payload.event_type,
            page_path=payload.page_path,
            details=details,
            created_at=taipei_now(),
        )
    )
    db.commit()
    return None
