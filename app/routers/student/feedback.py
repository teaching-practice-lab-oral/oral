"""AI feedback on Draft 1 (stage 3 → 4) and final draft + shadowing TTS generation (stage 4 → 5)."""
import asyncio
import hashlib
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import get_current_student
from app.database import get_db
from app.models import User, Submission
from app.services.prompt_composition import compose_stage_prompt
from app.services.submission_data import (
    hydrate_submission_from_normalized,
    get_job_profile_data,
    job_profile_context,
    list_answers,
    list_shadowing_tts_keys,
    replace_answers,
    replace_shadowing_tts_keys,
)
from app.schemas import (
    SubmissionResponse,
    FinalDraftAnswersRequest,
)
from app.services import rate_limiter, openai_chat
from app.services.input_validator import validate_draft_text
from app.services.openai_chat import (
    draft_feedback_response_format,
    extract_json_object,
    is_complete_draft_feedback,
    normalize_feedback,
)
from app.services.operation_lock import (
    FEEDBACK_OPERATION,
    acquire_operation_lock,
)
from app.services.shadowing_tts import generate_asset
from app.services.workflow_policy import CORE_QUESTION_COUNT
from app.services.submission_assets import (
    delete_uncommitted_object,
    enqueue_object_cleanup,
)
from ._common import (
    MAX_FEEDBACK_COUNT,
    bind_answers_to_snapshot,
    ensure_submission_stage,
    get_editable_submission_locked,
    inject_questions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/student", tags=["student"])


def _answers_fingerprint(answers: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(answers, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _feedback_input_fingerprint(
    db: Session,
    sub: Submission,
    draft1_answers: list[dict] | None = None,
) -> str:
    profile = get_job_profile_data(db, sub) or {}
    payload = {
        # list_answers includes the snapshotted question text and its answer.
        "draft1": draft1_answers if draft1_answers is not None else list_answers(db, sub, "draft1"),
        "job_profile": {
            key: profile.get(key)
            for key in (
                "desired_position",
                "role_description",
                "required_competencies",
                "additional_notes",
            )
        },
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _feedback_request_data(
    db: Session,
    sub: Submission,
    draft1_answers: list[dict],
) -> tuple[str, str]:
    base_prompt = compose_stage_prompt(db, sub.assignment_id, 3)
    system_prompt, user_message = inject_questions(base_prompt, draft1_answers)
    return system_prompt, user_message + job_profile_context(db, sub)


def _require_feedback_ready(sub: Submission) -> None:
    ensure_submission_stage(sub, {4}, "請先完成 AI 寫作回饋，再撰寫最終草稿。")
    if not sub.draft2_ai_feedback or (sub.feedback_count or 0) < 1:
        raise HTTPException(status_code=409, detail="請先取得 AI 寫作回饋。")


@router.post("/submissions/{submission_id}/feedback/stream")
async def get_ai_feedback_stream(
    submission_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    sub = get_editable_submission_locked(db, submission_id, current_user.id)
    ensure_submission_stage(sub, {3, 4}, "目前階段無法取得或重新產生 AI 寫作回饋。")
    draft1_answers = list_answers(db, sub, "draft1")
    if not get_job_profile_data(db, sub):
        raise HTTPException(status_code=409, detail="請先完成欲應徵的職位資料")
    if len(draft1_answers) != CORE_QUESTION_COUNT:
        raise HTTPException(status_code=400, detail="請先完成固定題組的全部 4 題草稿。")
    if sub.feedback_count >= MAX_FEEDBACK_COUNT:
        raise HTTPException(status_code=400, detail=f"已達 AI 練習回饋次數上限（{MAX_FEEDBACK_COUNT} 次）")
    expected_input_fingerprint = _feedback_input_fingerprint(db, sub, draft1_answers)

    lease = await acquire_operation_lock(submission_id, FEEDBACK_OPERATION)
    try:
        rate_limiter.check_rate_limit(db, current_user.id, 3)
        system_prompt, user_message = _feedback_request_data(db, sub, draft1_answers)
        user_id = current_user.id
        rate_limiter.log_api_call(db, user_id, 3)
        # Release the FOR UPDATE lock before streaming to prevent deadlock with
        # _save_feedback's db2 session. The dedicated advisory-lock connection
        # remains held until the stream generator finishes or is cancelled.
        db.rollback()
    except Exception:
        await lease.release()
        raise

    async def generate():
        try:
            accumulated = []
            try:
                async for chunk in openai_chat.chat_completion_json_stream(
                    system_prompt,
                    user_message,
                    response_format=draft_feedback_response_format(len(draft1_answers)),
                ):
                    accumulated.append(chunk)
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            except Exception as e:
                logger.error("Feedback stream error for submission %s: %s", submission_id, e)
                yield f"data: {json.dumps({'error': 'AI 練習回饋發生錯誤，請稍後再試。'})}\n\n"
                return

            full_text = "".join(accumulated)
            try:
                parsed = json.loads(full_text)
            except json.JSONDecodeError:
                parsed = extract_json_object(full_text)
            if not is_complete_draft_feedback(parsed, len(draft1_answers)):
                logger.warning(
                    "Rejected incomplete AI feedback for submission %s",
                    submission_id,
                )
                yield f"data: {json.dumps({'error': 'AI 回傳的回饋格式不完整，本次未寫入，請重試。'})}\n\n"
                return
            feedback_data = normalize_feedback(parsed, draft1_answers)

            # Run synchronous DB operations in a thread to avoid blocking the event loop
            def _save_feedback() -> tuple[bool, int]:
                from app.database import SessionLocal
                db2 = SessionLocal()
                try:
                    try:
                        sub2 = get_editable_submission_locked(db2, submission_id, user_id)
                    except HTTPException:
                        db2.rollback()
                        return False, 0
                    if (
                        sub2
                        and sub2.submitted_at is None
                        and sub2.stage in {3, 4}
                        and (sub2.feedback_count or 0) < MAX_FEEDBACK_COUNT
                        and _feedback_input_fingerprint(db2, sub2)
                        == expected_input_fingerprint
                    ):
                        sub2.draft2_ai_feedback = feedback_data
                        sub2.feedback_count = (sub2.feedback_count or 0) + 1
                        if sub2.stage < 4:
                            sub2.stage = 4
                        db2.commit()
                        return True, sub2.feedback_count
                    return False, sub2.feedback_count if sub2 else 0
                finally:
                    db2.close()

            feedback_saved, feedback_count = await asyncio.to_thread(_save_feedback)
            if not feedback_saved:
                yield f"data: {json.dumps({'error': '作答階段已更新，本次回饋未寫入，請重新整理。'})}\n\n"
                return

            yield f"data: {json.dumps({'done': True, 'feedback': feedback_data, 'feedback_count': feedback_count})}\n\n"
        finally:
            await lease.release()

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.put("/submissions/{submission_id}/final-draft", response_model=SubmissionResponse)
def save_final_draft_draft(
    submission_id: int,
    payload: FinalDraftAnswersRequest,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """Persist an incomplete final draft without advancing the workflow."""
    sub = get_editable_submission_locked(db, submission_id, current_user.id)
    _require_feedback_ready(sub)
    answers = bind_answers_to_snapshot(db, sub, payload.final_draft_answers, require_all=False)
    for item in answers:
        validate_draft_text(item["text"])
    replace_answers(db, sub, "final", answers)
    db.commit()
    db.refresh(sub)
    hydrate_submission_from_normalized(db, sub)
    return SubmissionResponse.model_validate(sub)


@router.post("/submissions/{submission_id}/final-draft", response_model=SubmissionResponse)
async def save_final_draft(
    submission_id: int,
    payload: FinalDraftAnswersRequest,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    sub = get_editable_submission_locked(db, submission_id, current_user.id)
    _require_feedback_ready(sub)
    answers = bind_answers_to_snapshot(db, sub, payload.final_draft_answers, require_all=True)
    for item in answers:
        validate_draft_text(item["text"])
    replace_answers(db, sub, "final", answers)

    student_id = current_user.student_id  # capture before releasing the session (avoids reload)
    old_tts_keys = [
        item.get("key")
        for item in list_shadowing_tts_keys(db, sub)
        if item.get("key")
    ]
    replace_shadowing_tts_keys(db, sub, [])
    enqueue_object_cleanup(db, old_tts_keys)

    # Reserve the next stage before releasing the row lock. A second tab can no longer
    # submit a different answer set while this request is generating deterministic TTS keys.
    sub.stage = 5
    expected_fingerprint = _answers_fingerprint(answers)

    # Feedback, final-draft TTS, missing-TTS recovery and shadowing uploads use
    # aliases of one preparation key. One lease prevents cross-route waste
    # without nesting dedicated advisory-lock connections.
    operation_lease = await acquire_operation_lock(submission_id, FEEDBACK_OPERATION)

    try:
        db.commit()
        assets = await asyncio.gather(
            *(
                generate_asset(
                    answers,
                    student_id,
                    submission_id,
                    i,
                    current_user.id,
                )
                for i in range(len(answers))
            )
        )

        # Re-open a short locked transaction and ensure the final answers still
        # match the set used for TTS.
        try:
            sub = get_editable_submission_locked(db, submission_id, current_user.id)
            ensure_submission_stage(sub, {5}, "最終草稿狀態已更新，請重新整理後再試。")
            current_answers = list_answers(db, sub, "final")
            if _answers_fingerprint(current_answers) != expected_fingerprint:
                raise HTTPException(status_code=409, detail="最終草稿已在其他分頁更新，請重新整理後再試。")
        except Exception:
            db.rollback()
            await asyncio.gather(
                *(
                    delete_uncommitted_object(asset["key"])
                    for asset in assets
                    if asset and asset.get("key")
                ),
                return_exceptions=True,
            )
            raise
        try:
            replace_shadowing_tts_keys(db, sub, [
                {
                    "index": i,
                    "key": asset.get("key") if asset else None,
                    "timing": asset.get("timing") if asset else None,
                }
                for i, asset in enumerate(assets)
            ])
            db.commit()
        except Exception:
            db.rollback()
            await asyncio.gather(
                *(
                    delete_uncommitted_object(asset["key"])
                    for asset in assets
                    if asset and asset.get("key")
                ),
                return_exceptions=True,
            )
            raise
        db.refresh(sub)
        hydrate_submission_from_normalized(db, sub)
        return SubmissionResponse.model_validate(sub)
    finally:
        await operation_lease.release()
