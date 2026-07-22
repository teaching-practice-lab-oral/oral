"""Student job-profile and personalized-scaffold endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_student
from app.database import get_db
from app.models import User
from app.schemas import (
    JobProfilePayload,
    JobProfileResponse,
    LearningScaffoldGenerateResponse,
)
from app.services import openai_chat, rate_limiter
from app.services.learning_scaffold import (
    build_scaffold_request,
    learning_scaffold_state,
    normalize_scaffold_output,
    save_learning_scaffold,
    scaffold_input_hash,
    scaffold_response_format,
)
from app.services.operation_lock import (
    FEEDBACK_OPERATION,
    SCAFFOLD_OPERATION,
    acquire_operation_lock,
)
from app.services.submission_data import (
    get_job_profile_data,
    get_job_profile_prefill_data,
    upsert_job_profile,
)
from ._common import get_editable_submission_locked, get_own_submission
from app.utils import taipei_now


router = APIRouter(prefix="/api/student", tags=["student-job-profile"])
logger = logging.getLogger(__name__)


@router.get("/submissions/{submission_id}/job-profile/prefill", response_model=JobProfilePayload | None)
def get_job_profile_prefill(
    submission_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_own_submission(db, submission_id, current_user.id)
    return get_job_profile_prefill_data(db, submission)


@router.put("/submissions/{submission_id}/job-profile", response_model=JobProfileResponse)
async def save_job_profile(
    submission_id: int,
    payload: JobProfilePayload,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_editable_submission_locked(db, submission_id, current_user.id)
    existing = get_job_profile_data(db, submission)
    if existing and (submission.feedback_count or 0) > 0:
        raise HTTPException(status_code=409, detail="第一次 AI 寫作回饋已產生，職位資料已鎖定")
    lease = await acquire_operation_lock(submission_id, FEEDBACK_OPERATION)
    try:
        upsert_job_profile(db, submission, payload.model_dump())
        if submission.stage <= 1:
            submission.stage = 2
        db.commit()
        db.refresh(submission)
        return JobProfileResponse(**get_job_profile_data(db, submission))
    finally:
        await lease.release()


@router.post(
    "/submissions/{submission_id}/learning-scaffold",
    response_model=LearningScaffoldGenerateResponse,
)
async def generate_learning_scaffold(
    submission_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_editable_submission_locked(db, submission_id, current_user.id)
    if not get_job_profile_data(db, submission):
        raise HTTPException(status_code=409, detail="請先完成欲應徵的職位資料")
    state, existing = learning_scaffold_state(db, submission)
    if state == "not_applicable":
        raise HTTPException(status_code=409, detail="個人化鷹架只適用於公版題組")
    if state == "ready":
        return LearningScaffoldGenerateResponse(scaffold=existing)

    lease = await acquire_operation_lock(submission_id, SCAFFOLD_OPERATION)
    try:
        expected_hash = scaffold_input_hash(db, submission)
        if not expected_hash:
            raise HTTPException(status_code=409, detail="公版題目或職位資料不完整")
        question_set_key = submission.question_set_key
        try:
            system_prompt, user_message, blueprints = build_scaffold_request(db, submission)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        rate_limiter.reserve_api_call(current_user.id, 1)
        # The quota reservation owns a separate short transaction. Explicitly
        # release this route's row lock before the slow external request.
        db.rollback()
        try:
            raw = await openai_chat.chat_completion_json(
                system_prompt,
                user_message,
                temperature=0,
                response_format=scaffold_response_format(),
            )
            content = normalize_scaffold_output(
                raw,
                question_set_key=question_set_key,
                blueprints=blueprints,
            )
        except Exception as exc:
            logger.error(
                "OpenAI failed generating learning scaffold for submission %s: %s",
                submission_id,
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail="個人化提示暫時無法產生；職位資料已儲存，可使用公版提示繼續。",
            ) from exc

        db.expire_all()
        current = get_editable_submission_locked(db, submission_id, current_user.id)
        if scaffold_input_hash(db, current) != expected_hash:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="職位資料或題目已更新，請重新產生個人化提示。",
            )
        generated_at = taipei_now()
        scaffold = save_learning_scaffold(
            db,
            current,
            content,
            expected_hash,
            generated_at,
        )
        db.commit()
        return LearningScaffoldGenerateResponse(scaffold=scaffold)
    finally:
        await lease.release()
