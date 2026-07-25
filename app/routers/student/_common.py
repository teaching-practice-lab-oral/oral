"""Shared constants and helpers for the student router sub-package."""
from fastapi import HTTPException

from app.db_helpers import get_submission_or_403, get_submission_locked_or_403, ensure_not_submitted
from app.models import Submission, User
from app.services import storage
from app.services.student_assignment_access import ensure_student_can_mutate_submission_assignment
from app.services.submission_data import list_question_snapshot
from app.services.workflow_policy import (
    CORE_QUESTION_COUNT,
    WORKFLOW_LIMITS,
)
from app.utils import PRESIGNED_URL_EXPIRATION, taipei_now

MAX_ATTEMPTS = WORKFLOW_LIMITS.max_attempts
MAX_FEEDBACK_COUNT = WORKFLOW_LIMITS.max_feedback_count
MAX_SHADOWING_ATTEMPTS = WORKFLOW_LIMITS.max_shadowing_attempts

get_own_submission = get_submission_or_403
get_own_submission_locked = get_submission_locked_or_403


def bind_answers_to_snapshot(db, submission: Submission, items, *, require_all: bool) -> list[dict]:
    """Use immutable snapshot text for every saved answer; never trust client question text."""
    questions = list_question_snapshot(db, submission)
    if len(questions) != CORE_QUESTION_COUNT:
        raise HTTPException(
            status_code=409,
            detail=f"此嘗試的 {CORE_QUESTION_COUNT} 題快照不完整，請聯絡老師。",
        )
    answers = []
    seen = set()
    for item in items:
        index = int(item.index)
        if index in seen or index < 0 or index >= len(questions):
            raise HTTPException(status_code=400, detail="題目索引無效或重複。")
        seen.add(index)
        answers.append({"index": index, "question": questions[index], "text": item.text})
    if not answers:
        raise HTTPException(status_code=400, detail="至少需要填寫一題。")
    if require_all and seen != set(range(len(questions))):
        raise HTTPException(
            status_code=400,
            detail=f"請完成固定題組的全部 {CORE_QUESTION_COUNT} 題。",
        )
    return sorted(answers, key=lambda answer: answer["index"])


def ensure_before_due(sub: Submission) -> None:
    """Raise HTTP 403 once the assignment deadline has passed.

    After the due date a submission becomes read-only unless the student has been
    granted a late-submission deadline (sub.late_deadline) that has not yet expired.
    """
    due = sub.assignment.due_date if sub.assignment else None
    if due and taipei_now() > due:
        late = sub.late_deadline
        if not late or taipei_now() > late:
            raise HTTPException(status_code=403, detail="作業已截止，僅可檢視，無法繼續作答或修改。")


def start_practice_timer(sub: Submission) -> bool:
    """Record when active practice starts; practice is no longer time-limited."""
    if sub.submitted_at or sub.stage >= 8:
        return False
    changed = False
    if sub.practice_started_at is None:
        sub.practice_started_at = taipei_now()
        changed = True
    if sub.practice_deadline_at is not None:
        sub.practice_deadline_at = None
        changed = True
    return changed


def ensure_submission_stage(sub: Submission, allowed_stages: set[int], detail: str) -> None:
    """Reject mutations that do not belong to the submission's current workflow stage."""
    if sub.stage not in allowed_stages:
        raise HTTPException(status_code=409, detail=detail)


def get_editable_submission_locked(db, submission_id: int, user_id: int) -> Submission:
    """Row-lock the caller's own submission and assert it is still editable.

    The standard prelude for every stage-advancing student endpoint — replaces the repeated
    `sub = get_own_submission_locked(...); ensure_not_submitted(sub)` pair, and additionally
    enforces the assignment deadline so finalized *or* past-due submissions are read-only.
    """
    sub = get_submission_locked_or_403(db, submission_id, user_id)
    ensure_not_submitted(sub)
    assignment = sub.assignment
    student = db.query(User).filter(User.id == user_id).first()
    ensure_student_can_mutate_submission_assignment(assignment, student)
    ensure_before_due(sub)
    return sub


def presigned_or_404(key: str | None) -> dict:
    """Return a presigned-URL response for an object key, or raise 404 if absent."""
    if not key or not storage.is_current_object_key(key, "audio"):
        raise HTTPException(status_code=404, detail="Audio not found")
    return {"url": storage.generate_presigned_url(key, expiration=PRESIGNED_URL_EXPIRATION)}


def entry_key(items, match_value, key_field, match_field="index"):
    """Return key_field of the first list entry whose match_field == match_value, else None."""
    for item in items or []:
        if item.get(match_field) == match_value:
            return item.get(key_field)
    return None


def build_questions_block(answers: list) -> str:
    """Format per-question answers into a block for the AI prompt."""
    return "\n".join(
        f"Q{i+1}: {a['question']}\nA{i+1}: {a['text']}"
        for i, a in enumerate(answers)
    )


def inject_questions(system_prompt: str, answers: list) -> tuple[str, str]:
    """Return (system_prompt_with_questions, user_message)."""
    if answers:
        block = build_questions_block(answers)
        prompt = system_prompt.replace("{questions}", block)
        return prompt, block
    # No answers means the placeholder line is omitted from the prompt.
    lines = [l for l in system_prompt.splitlines() if "{questions}" not in l]
    return "\n".join(lines), ""
