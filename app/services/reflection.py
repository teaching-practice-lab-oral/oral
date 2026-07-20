"""Reflection draft concurrency, validation, and lifecycle rules."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Submission, SubmissionReflection
from app.services.submission_data import (
    REFLECTION_QUESTIONS,
    get_reflection_data,
    replace_reflection,
)


def get_reflection_row(db: Session, submission_id: int) -> SubmissionReflection | None:
    return (
        db.query(SubmissionReflection)
        .filter(SubmissionReflection.submission_id == submission_id)
        .first()
    )


def _conflict(db: Session, submission: Submission) -> HTTPException:
    latest = get_reflection_data(db, submission) or {
        "revision": 0,
        "questions": list(REFLECTION_QUESTIONS),
        "answers": [""] * len(REFLECTION_QUESTIONS),
        "has_issue": False,
        "issue_category": None,
        "issue_description": None,
        "has_photo": False,
        "photo_original_name": None,
        "submitted_at": None,
        "updated_at": None,
    }
    return HTTPException(
        status_code=409,
        detail={
            "code": "reflection_revision_conflict",
            "message": "心得已在其他分頁更新，請選擇要保留的版本。",
            "latest": latest,
        },
    )


def require_revision(
    db: Session,
    submission: Submission,
    expected_revision: int,
    *,
    require_existing: bool = False,
) -> SubmissionReflection | None:
    row = get_reflection_row(db, submission.id)
    if row is None:
        if require_existing or expected_revision != 0:
            raise _conflict(db, submission)
        return None
    if row.revision != expected_revision:
        raise _conflict(db, submission)
    return row


def save_draft(
    db: Session,
    submission: Submission,
    data: dict,
    expected_revision: int,
) -> SubmissionReflection:
    existing = require_revision(db, submission, expected_revision)
    row = replace_reflection(db, submission, data)
    if existing is not None:
        row.revision += 1
    return row


def get_or_create_for_photo(
    db: Session,
    submission: Submission,
    expected_revision: int,
) -> SubmissionReflection:
    row = require_revision(db, submission, expected_revision)
    if row is None:
        return replace_reflection(
            db,
            submission,
            {"answers": [""] * len(REFLECTION_QUESTIONS)},
        )
    row.revision += 1
    return row


def require_existing_mutation(
    db: Session,
    submission: Submission,
    expected_revision: int,
) -> SubmissionReflection:
    row = require_revision(
        db,
        submission,
        expected_revision,
        require_existing=True,
    )
    assert row is not None
    row.revision += 1
    return row


def validate_for_submission(row: SubmissionReflection) -> None:
    answers_by_index = {
        answer.question_index: answer.answer_text.strip()
        for answer in row.answers
    }
    expected_indices = set(range(len(REFLECTION_QUESTIONS)))
    if set(answers_by_index) != expected_indices or any(
        not answers_by_index[index] for index in expected_indices
    ):
        raise HTTPException(
            status_code=400,
            detail=f"{len(REFLECTION_QUESTIONS)} 題心得均為必填",
        )
    if row.has_issue and (
        not (row.issue_category or "").strip()
        or not (row.issue_description or "").strip()
    ):
        raise HTTPException(status_code=400, detail="請完整填寫問題類別與說明")
