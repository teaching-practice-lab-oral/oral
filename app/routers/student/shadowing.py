"""Student per-question shadowing recordings (stage 5 → 6)."""
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.auth import get_current_student
from app.database import get_db
from app.db_helpers import advance_submission_stage
from app.models import User
from app.services.submission_data import (
    list_answers,
    list_shadowing_question_entries,
    upsert_shadowing_record,
)
from app.services.operation_lock import SHADOWING_OPERATION, acquire_operation_lock
from app.schemas import ShadowingQuestionRecordingResponse
from app.services import audio_processor, rate_limiter, worker_client
from app.services.submission_assets import (
    delete_uncommitted_object,
    enqueue_object_cleanup,
)
from ._common import MAX_SHADOWING_ATTEMPTS, ensure_submission_stage, get_editable_submission_locked

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/student", tags=["student"])


@router.post("/submissions/{submission_id}/speaking1/{question_index}", response_model=ShadowingQuestionRecordingResponse)
async def speaking1_shadowing_question(
    submission_id: int,
    question_index: int,
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    sub = get_editable_submission_locked(db, submission_id, current_user.id)
    ensure_submission_stage(sub, {5}, "目前階段無法新增或重錄跟讀音訊。")

    final_answers = list_answers(db, sub, "final")
    num_questions = len(final_answers)
    if question_index < 0 or question_index >= num_questions:
        raise HTTPException(status_code=400, detail="Invalid question index")

    questions_data = list_shadowing_question_entries(db, sub)
    recorded_indices = {q["index"] for q in questions_data}

    if question_index > 0 and (question_index - 1) not in recorded_indices:
        raise HTTPException(status_code=400, detail="請依序完成前一題的錄音")

    existing = next((q for q in questions_data if q["index"] == question_index), None)
    current_attempts = existing["attempts"] if existing else 0
    if current_attempts + 1 > MAX_SHADOWING_ATTEMPTS:
        raise HTTPException(
            status_code=400,
            detail=f"最多只能錄音 {MAX_SHADOWING_ATTEMPTS} 次",
        )

    # The last question can advance the whole submission to stage 6.  Use one
    # submission-wide lease so a simultaneous re-record of another question is
    # rejected before either request spends on transcription.
    lease = await acquire_operation_lock(submission_id, SHADOWING_OPERATION)
    try:
        # The operation lease remains held while local validation and external
        # processing run, but the ordinary row lock is released first.
        student_id = current_user.student_id
        key_stem = f"shadowing_recording_q{question_index}_{uuid4().hex}"
        db.rollback()
        prepared_audio = await audio_processor.prepare_audio_upload(audio, key_stem)
        rate_limiter.reserve_api_call(current_user.id, 5)

        with worker_client.routing_context(
            user_id=current_user.id,
            student_id=student_id,
            submission_id=submission_id,
            stage=5,
            operation="shadowing_audio",
        ):
            audio_key, transcript, metrics = await audio_processor.process_prepared_audio(
                prepared_audio,
                student_id,
                submission_id,
                key_stem,
            )

        # Re-check mutable preconditions under a fresh row lock before accepting
        # the unique temporary object.
        old_audio_key = None
        try:
            sub = get_editable_submission_locked(db, submission_id, current_user.id)
            ensure_submission_stage(sub, {5}, "跟讀狀態已更新，請重新整理後再試。")
            questions_data = list_shadowing_question_entries(db, sub)
            recorded_indices = {q["index"] for q in questions_data}
            if question_index > 0 and (question_index - 1) not in recorded_indices:
                raise HTTPException(status_code=409, detail="前一題狀態已更新，請重新整理後再試。")
            prior = next((q for q in questions_data if q["index"] == question_index), None)
            fresh_attempts = prior["attempts"] if prior else 0
            if fresh_attempts >= MAX_SHADOWING_ATTEMPTS:
                raise HTTPException(status_code=409, detail="此題已達錄音次數上限，請重新整理。")
            new_attempts = fresh_attempts + 1
            old_audio_key = prior.get("audio_key") if prior else None
            entry = {
                "index": question_index,
                "audio_key": audio_key,
                "transcript": transcript,
                "metrics": metrics or None,
                "attempts": new_attempts,
            }
            questions_data = [q for q in questions_data if q["index"] != question_index]
            questions_data.append(entry)
            questions_data.sort(key=lambda q: q["index"])
            upsert_shadowing_record(db, sub, entry)
            if old_audio_key and old_audio_key != audio_key:
                enqueue_object_cleanup(db, [old_audio_key])
            all_done = len({q["index"] for q in questions_data}) >= num_questions
            if all_done:
                advance_submission_stage(sub, 6)
            db.commit()
        except Exception:
            db.rollback()
            await delete_uncommitted_object(audio_key)
            raise
        return ShadowingQuestionRecordingResponse(
            index=question_index,
            transcript=transcript,
            audio_key=audio_key,
            attempts=new_attempts,
            all_done=all_done,
        )
    finally:
        await lease.release()
