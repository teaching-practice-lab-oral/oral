"""Ownership and migration policy for per-attempt question snapshots."""

from sqlalchemy.orm import Session, selectinload

from app.models import Assignment, Submission
from app.services.submission_data import replace_question_snapshot


def question_snapshot_is_pristine(submission: Submission) -> bool:
    """Return whether an unfinished attempt has no question-bound learner work."""
    return bool(
        submission.submitted_at is None
        and not submission.draft2_ai_feedback
        and not submission.answer_rows
        and not submission.shadowing_records
        and not submission.roleplay_turn_rows
        and submission.report_row is None
    )


def sync_pristine_question_snapshots(db: Session, assignment: Assignment) -> int:
    """Move only untouched attempts to an assignment's newly selected questions."""
    submissions = (
        db.query(Submission)
        .filter(
            Submission.assignment_id == assignment.id,
            Submission.submitted_at.is_(None),
        )
        .options(
            selectinload(Submission.answer_rows),
            selectinload(Submission.shadowing_records),
            selectinload(Submission.roleplay_turn_rows),
            selectinload(Submission.report_row),
        )
        .all()
    )
    questions = list(assignment.questions or [])
    updated = 0
    for submission in submissions:
        if not question_snapshot_is_pristine(submission):
            continue
        submission.question_set_key = assignment.question_set_key
        replace_question_snapshot(db, submission, questions)
        updated += 1
    return updated
