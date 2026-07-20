from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import Rubric, RubricVersion, SubmissionGradeRevision


def submission_is_complete_for_grading(submission) -> bool:
    """Require the current workflow's formal-completion stage."""
    return bool(submission.submitted_at) and int(submission.stage or 0) >= 9


def default_published_rubric_version(db: Session) -> RubricVersion | None:
    return (
        db.query(RubricVersion)
        .join(Rubric, Rubric.id == RubricVersion.rubric_id)
        .filter(
            Rubric.is_system == True,
            Rubric.is_archived == False,
            RubricVersion.status == "published",
        )
        .order_by(RubricVersion.version_number.desc())
        .first()
    )


def published_rubric_version(db: Session, version_id: int | None) -> RubricVersion | None:
    if version_id is None:
        return default_published_rubric_version(db)
    return (
        db.query(RubricVersion)
        .join(Rubric, Rubric.id == RubricVersion.rubric_id)
        .filter(
            RubricVersion.id == version_id,
            RubricVersion.status == "published",
            Rubric.is_archived == False,
        )
        .first()
    )


def rubric_version_payload(version: RubricVersion) -> dict:
    rubric = version.rubric
    return {
        "rubric_id": rubric.id,
        "rubric_name": rubric.name,
        "description": rubric.description,
        "is_system": bool(rubric.is_system),
        "is_archived": bool(rubric.is_archived),
        "version_id": version.id,
        "version_number": version.version_number,
        "status": version.status,
        "definition": version.definition,
        "created_at": version.created_at,
        "published_at": version.published_at,
    }


def latest_grade(db: Session, submission_id: int) -> SubmissionGradeRevision | None:
    return (
        db.query(SubmissionGradeRevision)
        .filter(SubmissionGradeRevision.origin_submission_id == submission_id)
        .order_by(SubmissionGradeRevision.revision_number.desc(), SubmissionGradeRevision.id.desc())
        .first()
    )


def latest_grades_by_submission(db: Session, submission_ids: Iterable[int]) -> dict[int, SubmissionGradeRevision]:
    ids = list({int(value) for value in submission_ids})
    if not ids:
        return {}
    rows = (
        db.query(SubmissionGradeRevision)
        .filter(SubmissionGradeRevision.origin_submission_id.in_(ids))
        .order_by(
            SubmissionGradeRevision.origin_submission_id,
            SubmissionGradeRevision.revision_number.desc(),
            SubmissionGradeRevision.id.desc(),
        )
        .all()
    )
    result: dict[int, SubmissionGradeRevision] = {}
    for row in rows:
        result.setdefault(row.origin_submission_id, row)
    return result


def grade_admin_payload(row: SubmissionGradeRevision) -> dict:
    return {
        "id": row.id,
        "revision_number": row.revision_number,
        "rubric_version_id": row.rubric_version_id,
        "rubric_name": row.rubric_name,
        "rubric_version_number": row.rubric_version_number,
        "rubric_snapshot": row.rubric_snapshot,
        "ratings": row.ratings_json,
        "rubric_score": float(row.rubric_score),
        "final_score": float(row.final_score),
        "teacher_comment": row.teacher_comment,
        "teacher_feedback": row.teacher_feedback,
        "change_reason": row.change_reason,
        "grader_student_id": row.grader_student_id,
        "grader_name": row.grader_name,
        "created_at": row.created_at,
    }


def grade_student_payload(row: SubmissionGradeRevision) -> dict:
    public_ratings = []
    for item in row.ratings_json or []:
        public_ratings.append({
            key: item.get(key)
            for key in (
                "dimension_key", "dimension_name", "criterion_key", "criterion_name",
                "criterion_description", "level", "level_label", "level_anchor",
            )
        })
    return {
        "revision_number": row.revision_number,
        "rubric_name": row.rubric_name,
        "rubric_version_number": row.rubric_version_number,
        "ratings": public_ratings,
        "final_score": float(row.final_score),
        "teacher_comment": row.teacher_comment,
        "teacher_feedback": row.teacher_feedback,
        "graded_at": row.created_at,
    }


def grade_student_history_payload(row: SubmissionGradeRevision) -> dict:
    """Expose an auditable grade revision without admin-only scoring internals."""
    return {
        **grade_student_payload(row),
        "change_reason": row.change_reason,
        "grader_student_id": row.grader_student_id,
        "grader_name": row.grader_name,
    }


def score_differs(rubric_score: Decimal, final_score: float) -> bool:
    return abs(rubric_score - Decimal(str(final_score))) >= Decimal("0.05")
