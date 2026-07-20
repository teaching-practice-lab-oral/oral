"""Assignment question-source policy.

Question selection, materialisation and attempt-snapshot migration must remain
one operation.  This prevents admin CRUD and preset synchronisation from
quietly applying different rules.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Assignment
from app.question_sets import (
    DEFAULT_QUESTION_SET_KEY,
    normalize_custom_questions,
    question_set_questions,
)
from app.services.question_snapshot_policy import sync_pristine_question_snapshots


class AssignmentQuestionPolicyError(ValueError):
    """Raised when an assignment question source is invalid or ambiguous."""


@dataclass(frozen=True)
class AssignmentQuestionSelection:
    question_set_key: str | None
    questions: list[str]


def _public_selection(key: str) -> AssignmentQuestionSelection:
    try:
        return AssignmentQuestionSelection(key, question_set_questions(key))
    except KeyError as exc:
        raise AssignmentQuestionPolicyError("找不到指定的公版題組") from exc


def _custom_selection(questions) -> AssignmentQuestionSelection:
    try:
        return AssignmentQuestionSelection(None, normalize_custom_questions(questions))
    except ValueError as exc:
        raise AssignmentQuestionPolicyError(str(exc)) from exc


def selection_for_create(payload) -> AssignmentQuestionSelection:
    fields = payload.model_fields_set
    if payload.question_set_key:
        if "questions" in fields and payload.questions is not None:
            raise AssignmentQuestionPolicyError("公版題組與自訂題目不可同時提供")
        return _public_selection(payload.question_set_key)
    if payload.questions is not None:
        return _custom_selection(payload.questions)
    return _public_selection(DEFAULT_QUESTION_SET_KEY)


def selection_for_update(assignment: Assignment, payload) -> AssignmentQuestionSelection | None:
    fields = payload.model_fields_set
    has_key = "question_set_key" in fields
    has_questions = "questions" in fields
    if not has_key and not has_questions:
        return None
    if payload.question_set_key:
        if has_questions and payload.questions is not None:
            raise AssignmentQuestionPolicyError("公版題組與自訂題目不可同時提供")
        return _public_selection(payload.question_set_key)
    if has_questions and payload.questions is not None:
        return _custom_selection(payload.questions)
    if has_questions and payload.questions is None:
        return _public_selection(DEFAULT_QUESTION_SET_KEY)
    return _custom_selection(assignment.questions)


def selection_for_preset_repair(
    assignment: Assignment,
    preset_key: str,
) -> AssignmentQuestionSelection:
    """Preserve valid teacher choices; repair only missing or invalid sources."""
    if assignment.question_set_key:
        try:
            return _public_selection(assignment.question_set_key)
        except AssignmentQuestionPolicyError:
            return _public_selection(preset_key)
    try:
        return _custom_selection(assignment.questions)
    except AssignmentQuestionPolicyError:
        return _public_selection(preset_key)


def apply_selection(
    db: Session,
    assignment: Assignment,
    selection: AssignmentQuestionSelection,
    *,
    sync_attempts: bool,
) -> bool:
    """Materialise a source and atomically migrate only pristine attempts."""
    changed = (
        assignment.question_set_key != selection.question_set_key
        or list(assignment.questions or []) != selection.questions
    )
    if not changed:
        return False
    assignment.question_set_key = selection.question_set_key
    assignment.questions = list(selection.questions)
    if sync_attempts and assignment.id is not None:
        sync_pristine_question_snapshots(db, assignment)
    return True
