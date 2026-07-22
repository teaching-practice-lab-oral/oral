"""Presigned-URL retrieval for stored audio (shadowing TTS, recordings, roleplay)."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_student
from app.database import get_db
from app.models import User
from app.schemas import ShadowingTTSAudioResponse
from app.services import rate_limiter, tts_alignment
from app.services.shadowing_tts import generate_asset
from app.services.submission_assets import (
    delete_uncommitted_object,
    enqueue_object_cleanup,
)
from app.services.operation_lock import SHADOWING_TTS_OPERATION, acquire_operation_lock
from app.services.submission_data import (
    build_roleplay_conversation,
    get_shadowing_tts_entry,
    list_answers,
    list_shadowing_question_entries,
    list_shadowing_tts_keys,
    replace_shadowing_tts_keys,
)
from ._common import (
    ensure_submission_stage,
    get_own_submission,
    get_editable_submission_locked,
    presigned_or_404,
    entry_key,
)

router = APIRouter(prefix="/api/student", tags=["student"])
logger = logging.getLogger(__name__)


def _shadowing_tts_response(
    key: str | None,
    timing: dict | None,
) -> ShadowingTTSAudioResponse:
    url = presigned_or_404(key)["url"]
    cues = timing.get("cues") if isinstance(timing, dict) else None
    if timing and timing.get("status") == "ready" and isinstance(cues, list) and cues:
        try:
            return ShadowingTTSAudioResponse(url=url, sync_available=True, cues=cues)
        except Exception:
            logger.warning("Stored shadowing TTS timing is invalid", exc_info=True)
    return ShadowingTTSAudioResponse(url=url, sync_available=False, cues=[])


@router.get(
    "/submissions/{submission_id}/audio/shadowing-tts/{question_index}",
    response_model=ShadowingTTSAudioResponse,
)
async def get_audio_shadowing_tts_question(
    submission_id: int,
    question_index: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    sub = get_own_submission(db, submission_id, current_user.id)
    final_draft_answers = list_answers(db, sub, "final")
    if question_index < 0 or question_index >= len(final_draft_answers):
        raise HTTPException(status_code=404, detail="找不到這一題的示範音檔。")
    answer = final_draft_answers[question_index]
    spoken_text = tts_alignment.build_shadowing_tts_text(answer, question_index)
    entry = get_shadowing_tts_entry(db, sub, question_index)
    key = entry.get("key") if entry else None
    timing = entry.get("timing") if entry else None
    if not key:
        raise HTTPException(status_code=404, detail="找不到這一題的示範音檔。")
    trusted_timing = timing if tts_alignment.timing_matches_source(timing, spoken_text) else None
    return _shadowing_tts_response(key, trusted_timing)


@router.post(
    "/submissions/{submission_id}/audio/shadowing-tts/{question_index}",
    response_model=ShadowingTTSAudioResponse,
)
async def prepare_audio_shadowing_tts_question(
    submission_id: int,
    question_index: int,
    force: bool = False,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    # Check ownership before waiting, but do not hold a row lock while another
    # generator owns the single-flight lease.
    sub = get_own_submission(db, submission_id, current_user.id)
    ensure_submission_stage(sub, {5}, "只有在跟讀練習階段才能補產生示範音檔。")
    db.rollback()
    lease = await acquire_operation_lock(submission_id, SHADOWING_TTS_OPERATION)
    try:
        sub = get_editable_submission_locked(db, submission_id, current_user.id)
        ensure_submission_stage(sub, {5}, "只有在跟讀練習階段才能補產生示範音檔。")
        final_draft_answers = list_answers(db, sub, "final")
        if question_index < 0 or question_index >= len(final_draft_answers):
            raise HTTPException(status_code=404, detail="找不到這一題的示範音檔。")
        answer = final_draft_answers[question_index]
        spoken_text = tts_alignment.build_shadowing_tts_text(answer, question_index)
        existing_entry = get_shadowing_tts_entry(db, sub, question_index)
        if (
            not force
            and existing_entry
            and existing_entry.get("key")
            and tts_alignment.timing_matches_source(
                existing_entry.get("timing"),
                spoken_text,
            )
        ):
            return _shadowing_tts_response(
                existing_entry["key"],
                existing_entry.get("timing"),
            )

        student_id = current_user.student_id
        db.rollback()
        rate_limiter.reserve_api_call(current_user.id, rate_limiter.ExternalApiStage.SHADOWING)
        asset = await generate_asset(
            final_draft_answers,
            student_id,
            submission_id,
            question_index,
            current_user.id,
        )
        if not asset or not asset.get("key"):
            raise HTTPException(status_code=503, detail="示範音訊產生失敗，請稍後再試。")
        key = asset["key"]
        timing = asset.get("timing")
        try:
            locked = get_editable_submission_locked(db, submission_id, current_user.id)
            ensure_submission_stage(locked, {5}, "跟讀練習狀態已更新，請重新整理後再試。")
            current_answers = list_answers(db, locked, "final")
            current_spoken_text = (
                tts_alignment.build_shadowing_tts_text(current_answers[question_index], question_index)
                if question_index < len(current_answers)
                else ""
            )
            if current_spoken_text != spoken_text:
                raise HTTPException(status_code=409, detail="最終草稿已更新，請重新整理後再試。")
            current_entry = get_shadowing_tts_entry(db, locked, question_index)
            old_key = current_entry.get("key") if current_entry else None
            items = list_shadowing_tts_keys(db, locked)
            for item in items:
                if item.get("index") == question_index:
                    item.update({"key": key, "timing": timing})
                    break
            else:
                items.append({"index": question_index, "key": key, "timing": timing})
            replace_shadowing_tts_keys(db, locked, items)
            if old_key and old_key != key:
                enqueue_object_cleanup(db, [old_key])
            db.commit()
        except Exception:
            db.rollback()
            await delete_uncommitted_object(key)
            raise
        return _shadowing_tts_response(key, timing)
    finally:
        await lease.release()


@router.get("/submissions/{submission_id}/audio/speaking1/{question_index}")
def get_audio_speaking1_question(
    submission_id: int,
    question_index: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    sub = get_own_submission(db, submission_id, current_user.id)
    return presigned_or_404(entry_key(list_shadowing_question_entries(db, sub), question_index, "audio_key"))


@router.get("/submissions/{submission_id}/audio/roleplay-tts/{turn_number}")
def get_audio_roleplay_tts(
    submission_id: int,
    turn_number: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    sub = get_own_submission(db, submission_id, current_user.id)
    turns = build_roleplay_conversation(db, sub).get("turns", [])
    return presigned_or_404(entry_key(turns, turn_number, "interviewer_tts_key", match_field="turn_number"))


@router.get("/submissions/{submission_id}/audio/roleplay/{turn_number}")
def get_audio_roleplay_turn(
    submission_id: int,
    turn_number: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    sub = get_own_submission(db, submission_id, current_user.id)
    turns = build_roleplay_conversation(db, sub).get("turns", [])
    return presigned_or_404(entry_key(turns, turn_number, "student_audio_key", match_field="turn_number"))
