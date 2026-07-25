"""Student reflection worksheet, photo and submission endpoints."""

import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import get_current_student
from app.config import settings
from app.database import get_db
from app.models import SubmissionReflection, User
from app.schemas import ReflectionPayload, ReflectionResponse, ReflectionSubmitRequest
from app.services import mail, reflection as reflection_service, storage
from app.services.submission_assets import delete_uncommitted_object, enqueue_object_cleanup
from app.services.submission_data import get_job_profile_data, get_reflection_data, report_input_hash
from app.utils import PRESIGNED_URL_EXPIRATION, taipei_now
from ._common import get_editable_submission_locked, get_own_submission


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/student", tags=["student-reflection"])
MAX_REFLECTION_PHOTO_BYTES = 10 * 1024 * 1024


async def _send_issue_notice_safe(*args) -> None:
    try:
        await mail.send_reflection_issue_notice(*args)
    except Exception:
        logger.exception("Reflection issue notification email failed")


def _reflection_or_404(db: Session, submission_id: int) -> SubmissionReflection:
    row = db.query(SubmissionReflection).filter(SubmissionReflection.submission_id == submission_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="尚未建立心得資料")
    return row


def _detect_image(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"heif"}:
            return ("image/heif", "heif") if brand == b"heif" else ("image/heic", "heic")
    raise HTTPException(status_code=400, detail="照片只接受 JPEG、PNG、WebP、HEIC 或 HEIF")


@router.put("/submissions/{submission_id}/reflection", response_model=ReflectionResponse)
def save_reflection_draft(
    submission_id: int,
    payload: ReflectionPayload,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_editable_submission_locked(db, submission_id, current_user.id)
    if submission.stage < 8:
        raise HTTPException(status_code=409, detail="請先完成 AI 回饋再填寫心得")
    reflection_service.save_draft(db, submission, payload.model_dump(exclude={"expected_revision"}), payload.expected_revision)
    db.commit()
    db.refresh(submission)
    return ReflectionResponse(**get_reflection_data(db, submission))


@router.post("/submissions/{submission_id}/reflection/photo", response_model=ReflectionResponse)
async def upload_reflection_photo(
    submission_id: int,
    photo: UploadFile = File(...),
    expected_revision: int = Form(..., ge=0),
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_editable_submission_locked(db, submission_id, current_user.id)
    if submission.stage < 8:
        raise HTTPException(status_code=409, detail="請先完成 AI 回饋")
    owned_submission_id = submission.id
    student_id = current_user.student_id
    db.rollback()
    data = await photo.read(MAX_REFLECTION_PHOTO_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="照片檔案不可為空")
    if len(data) > MAX_REFLECTION_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="照片不可超過 10 MB")
    content_type, extension = _detect_image(data)
    key = storage.object_key(
        "reflection",
        student_id,
        owned_submission_id,
        f"{uuid4().hex}.{extension}",
    )
    await storage.upload_file_async(key, data, content_type)
    try:
        submission = get_editable_submission_locked(db, submission_id, current_user.id)
    except Exception:
        await delete_uncommitted_object(key)
        raise
    try:
        row = reflection_service.get_or_create_for_photo(db, submission, expected_revision)
        db.flush()
    except Exception:
        db.rollback()
        await delete_uncommitted_object(key)
        raise
    old_key = row.photo_key
    row.photo_key = key
    row.photo_content_type = content_type
    row.photo_original_name = Path(photo.filename or f"photo.{extension}").name[:256]
    row.photo_size = len(data)
    row.updated_at = taipei_now()
    try:
        if old_key and old_key != key:
            enqueue_object_cleanup(db, [old_key])
        db.commit()
    except Exception:
        db.rollback()
        await delete_uncommitted_object(key)
        raise
    return ReflectionResponse(**get_reflection_data(db, submission))


@router.delete("/submissions/{submission_id}/reflection/photo", response_model=ReflectionResponse)
async def remove_reflection_photo(
    submission_id: int,
    expected_revision: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_editable_submission_locked(db, submission_id, current_user.id)
    row = reflection_service.require_existing_mutation(db, submission, expected_revision)
    old_key = row.photo_key
    row.photo_key = None
    row.photo_content_type = None
    row.photo_original_name = None
    row.photo_size = None
    if old_key:
        enqueue_object_cleanup(db, [old_key])
    db.commit()
    db.refresh(submission)
    return ReflectionResponse(**get_reflection_data(db, submission))


@router.get("/submissions/{submission_id}/reflection/photo-url")
def get_reflection_photo_url(
    submission_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_own_submission(db, submission_id, current_user.id)
    row = _reflection_or_404(db, submission.id)
    if (
        not row.photo_key
        or not storage.is_current_object_key(row.photo_key, "reflection")
    ):
        raise HTTPException(status_code=404, detail="沒有上傳照片")
    return {"url": storage.generate_presigned_url(row.photo_key, expiration=PRESIGNED_URL_EXPIRATION)}


@router.post("/submissions/{submission_id}/reflection/submit", response_model=ReflectionResponse)
def submit_reflection(
    submission_id: int,
    payload: ReflectionSubmitRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_editable_submission_locked(db, submission_id, current_user.id)
    if submission.stage < 8:
        raise HTTPException(status_code=409, detail="請先完成 AI 回饋")
    if not get_job_profile_data(db, submission):
        raise HTTPException(status_code=409, detail="請先補填欲應徵的職位資料")
    report_row = submission.report_row
    if not report_row or report_row.input_hash != report_input_hash(db, submission):
        raise HTTPException(status_code=409, detail="AI 回饋需要依職位資料重新產生後才能送出心得")
    row = reflection_service.require_existing_mutation(db, submission, payload.expected_revision)
    reflection_service.validate_for_submission(row)
    row.submitted_at = taipei_now()
    submission.stage = 9
    submission.submitted_at = row.submitted_at
    assignment = submission.assignment
    notice = None
    if row.has_issue:
        protected = db.query(User).filter(
            User.student_id == settings.PROTECTED_ADMIN_STUDENT_ID,
            User.role == "admin",
            User.is_active == True,
        ).first()
        if protected and protected.email:
            notice = (
                protected.email,
                current_user.name,
                current_user.student_id,
                assignment.title,
                row.issue_category or "其他",
                row.issue_description or "",
                f"{settings.PUBLIC_BASE_URL.rstrip('/')}/admin/assignments/{assignment.id}/students/{current_user.id}?submission={submission.id}",
            )
    db.commit()
    if notice:
        background_tasks.add_task(_send_issue_notice_safe, *notice)
    return ReflectionResponse(**get_reflection_data(db, submission))
