"""Authorized admin access to student media objects."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_admin
from app.database import get_db
from app.models import RoleplayTurn, ShadowingRecord, SubmissionReflection, User
from app.services import storage
from app.services.admin_submission_access import get_accessible_submission_context
from app.utils import PRESIGNED_URL_EXPIRATION


router = APIRouter(prefix="/api/admin", tags=["admin-media"])


def _find_submission_id_for_audio_key(db: Session, key: str) -> int | None:
    if (
        not key
        or len(key) > 512
        or not storage.is_current_object_key(key, "audio")
    ):
        return None
    row = db.query(ShadowingRecord.submission_id).filter(
        or_(ShadowingRecord.tts_key == key, ShadowingRecord.audio_key == key)
    ).first()
    if row:
        return row[0]
    row = db.query(RoleplayTurn.submission_id).filter(
        or_(RoleplayTurn.interviewer_tts_key == key, RoleplayTurn.student_audio_key == key)
    ).first()
    return row[0] if row else None


@router.get("/audio-url")
def get_audio_url(
    key: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    submission_id = _find_submission_id_for_audio_key(db, key)
    if submission_id is None:
        raise HTTPException(status_code=404, detail="Audio file not found")
    get_accessible_submission_context(db, admin, submission_id, hydrate=False)
    try:
        return {"url": storage.generate_presigned_url(key, expiration=PRESIGNED_URL_EXPIRATION)}
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Audio file not found") from exc


@router.get("/submissions/{submission_id}/reflection/photo-url")
def get_reflection_photo_url(
    submission_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    submission, _, _ = get_accessible_submission_context(db, admin, submission_id, hydrate=False)
    reflection = db.query(SubmissionReflection).filter(
        SubmissionReflection.submission_id == submission.id
    ).first()
    if (
        not reflection
        or not reflection.photo_key
        or not storage.is_current_object_key(reflection.photo_key, "reflection")
    ):
        raise HTTPException(status_code=404, detail="學生沒有上傳問題照片")
    return {"url": storage.generate_presigned_url(reflection.photo_key, expiration=PRESIGNED_URL_EXPIRATION)}
