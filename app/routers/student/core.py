"""Core student endpoints: assignment listing/detail, submission
lifecycle (start / detail / attempts), and Draft 1 (stage 2 → 3)."""
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_student
from app.config import settings
from app.database import get_db
from app.db_helpers import (
    get_assignment_or_404, get_latest_submission,
)
from app.models import User, Assignment, Submission, SubmissionGradeRevision
from app.question_sets import question_set_scaffold_blueprints
from app.services.student_assignment_access import (
    ensure_student_can_access_current_assignment,
    ensure_student_can_read_assignment_history,
    ensure_student_is_in_assignment_scope,
)
from app.services.submission_data import (
    get_job_profile_data,
    hydrate_submission_from_normalized,
    list_answers,
    question_snapshot_for_attempt,
    replace_answers,
    replace_question_snapshot,
)
from app.utils import taipei_now
from app.schemas import (
    StudentAssignmentItem,
    AssignmentWithSubmission,
    AssignmentResponse,
    SubmissionResponse,
    SubmissionHistoryItem,
    StudentGradeHistoryItem,
    Draft1AnswersRequest,
)
from app.services.grading import grade_student_history_payload, latest_grades_by_submission
from app.services.input_validator import validate_draft1_text
from app.services.operation_lock import FEEDBACK_OPERATION, acquire_operation_lock
from app.services.workflow_policy import workflow_limits_payload
from ._common import (
    MAX_ATTEMPTS,
    MAX_FEEDBACK_COUNT,
    bind_answers_to_snapshot,
    ensure_submission_stage,
    get_own_submission,
    get_editable_submission_locked,
    start_practice_timer,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/student", tags=["student"])


def _apply_draft1_version_transition(
    sub: Submission,
    current_answers: list[dict],
    updated_answers: list[dict],
) -> bool:
    """Keep the writing stage and its AI feedback bound to one draft version."""
    if current_answers == updated_answers:
        return False
    if sub.stage == 4 and sub.draft2_ai_feedback:
        if (sub.feedback_count or 0) >= MAX_FEEDBACK_COUNT:
            raise HTTPException(
                status_code=409,
                detail="AI 回饋次數已用完，為避免終稿引用不相符的回饋，草稿一已鎖定。",
            )
        sub.draft2_ai_feedback = None
    # A partial per-question save remains in the drafting stage.  Only the
    # complete immutable four-question snapshot unlocks AI feedback.
    sub.stage = 3 if len(updated_answers) == 4 else 2
    return True


def _assignment_history_flags(
    db: Session,
    user_id: int,
    assignment_ids: list[int],
) -> tuple[dict[int, int], set[int]]:
    """Batch-load each latest submitted attempt and whether grades exist."""
    from sqlalchemy import and_, func

    latest_submitted_attempt_sq = (
        db.query(
            Submission.assignment_id,
            func.max(Submission.attempt_number).label("max_attempt"),
        )
        .filter(
            Submission.user_id == user_id,
            Submission.assignment_id.in_(assignment_ids),
            Submission.submitted_at.isnot(None),
        )
        .group_by(Submission.assignment_id)
        .subquery()
    )
    latest_submitted_submission_ids = {
        assignment_id: submission_id
        for assignment_id, submission_id in (
            db.query(Submission.assignment_id, Submission.id)
            .join(
                latest_submitted_attempt_sq,
                and_(
                    Submission.assignment_id
                    == latest_submitted_attempt_sq.c.assignment_id,
                    Submission.attempt_number
                    == latest_submitted_attempt_sq.c.max_attempt,
                ),
            )
            .filter(Submission.user_id == user_id)
            .all()
        )
    }
    graded_assignment_ids = {
        row[0]
        for row in (
            db.query(Submission.assignment_id)
            .join(
                SubmissionGradeRevision,
                SubmissionGradeRevision.origin_submission_id == Submission.id,
            )
            .filter(
                Submission.user_id == user_id,
                Submission.assignment_id.in_(assignment_ids),
                Submission.submitted_at.isnot(None),
            )
            .distinct()
            .all()
        )
    }
    return latest_submitted_submission_ids, graded_assignment_ids


@router.get("/assignments", response_model=List[StudentAssignmentItem])
def list_assignments(
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    from sqlalchemy import and_, or_, cast
    from sqlalchemy.dialects.postgresql import JSONB
    student_class = current_user.course_num
    # Filter course_nums at DB level: open-to-all (NULL or []) or matches student's class
    open_to_all = or_(
        Assignment.course_nums.is_(None),
        cast(Assignment.course_nums, JSONB) == cast('null', JSONB),
        cast(Assignment.course_nums, JSONB) == cast('[]', JSONB),
    )
    if student_class:
        course_filter = or_(open_to_all, cast(Assignment.course_nums, JSONB).contains([student_class]))
    else:
        course_filter = open_to_all
    assignments = (
        db.query(Assignment)
        .filter(Assignment.is_active == True, course_filter)
        .order_by(Assignment.due_date.asc())
        .all()
    )
    if not assignments:
        return []

    assignment_ids = [a.id for a in assignments]

    # Fetch latest submission per assignment in one query using a subquery
    from sqlalchemy import func
    latest_attempt_sq = (
        db.query(
            Submission.assignment_id,
            func.max(Submission.attempt_number).label("max_attempt"),
        )
        .filter(
            Submission.user_id == current_user.id,
            Submission.assignment_id.in_(assignment_ids),
        )
        .group_by(Submission.assignment_id)
        .subquery()
    )
    latest_subs = (
        db.query(Submission)
        .join(
            latest_attempt_sq,
            and_(
                Submission.assignment_id == latest_attempt_sq.c.assignment_id,
                Submission.attempt_number == latest_attempt_sq.c.max_attempt,
                Submission.user_id == current_user.id,
            ),
        )
        .all()
    )
    sub_map = {s.assignment_id: s for s in latest_subs}
    latest_submitted_submission_ids, graded_assignment_ids = _assignment_history_flags(
        db,
        current_user.id,
        assignment_ids,
    )
    latest_submitted_grades = latest_grades_by_submission(
        db,
        latest_submitted_submission_ids.values(),
    )

    result = []
    for a in assignments:
        sub = sub_map.get(a.id)
        result.append(
            StudentAssignmentItem(
                id=a.id,
                title=a.title,
                description=a.description,
                start_date=a.start_date,
                due_date=a.due_date,
                late_deadline=sub.late_deadline if sub else None,
                current_stage=sub.stage if sub else 1,
                attempt_number=sub.attempt_number if sub else 0,
                is_submitted=sub.submitted_at is not None if sub else False,
                workflow_version=sub.workflow_version if sub else 2,
                has_job_profile=bool(sub and sub.job_profile),
                has_submission_history=a.id in latest_submitted_submission_ids,
                latest_submitted_submission_id=latest_submitted_submission_ids.get(a.id),
                result_export_submission_id=(
                    latest_submitted_submission_ids.get(a.id)
                    if latest_submitted_submission_ids.get(a.id) in latest_submitted_grades
                    else None
                ),
                has_grade_history=a.id in graded_assignment_ids,
                rubric_version_id=sub.rubric_version_id if sub else a.rubric_version_id,
            )
        )
    return result


@router.get("/assignments/{assignment_id}", response_model=AssignmentWithSubmission)
def get_assignment_detail(
    assignment_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    assignment = get_assignment_or_404(db, assignment_id)
    ensure_student_can_access_current_assignment(assignment, current_user)
    sub = get_latest_submission(db, current_user.id, assignment_id)
    assignment_response = AssignmentResponse.model_validate(assignment)
    hydrate_submission_from_normalized(db, sub)
    if sub and sub.questions_snapshot is not None:
        assignment_response = assignment_response.model_copy(
            update={
                "questions": sub.questions_snapshot,
                "question_set_key": sub.question_set_key,
            }
        )
    scaffold_key = sub.question_set_key if sub else assignment.question_set_key
    if scaffold_key:
        try:
            question_scaffolds = [
                {"index": index, **item}
                for index, item in enumerate(question_set_scaffold_blueprints(scaffold_key))
            ]
            assignment_response = assignment_response.model_copy(
                update={"question_scaffolds": question_scaffolds}
            )
        except KeyError:
            pass
    return AssignmentWithSubmission(
        assignment=assignment_response,
        submission=SubmissionResponse.model_validate(sub) if sub else None,
        workflow_limits=workflow_limits_payload(),
    )


@router.post("/submissions/{submission_id}/practice/start", status_code=204)
def begin_practice_session(
    submission_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    submission = get_editable_submission_locked(db, submission_id, current_user.id)
    if submission.stage >= 8:
        raise HTTPException(status_code=409, detail="目前階段不需要啟動練習模式。")
    if start_practice_timer(submission):
        db.commit()
    else:
        db.rollback()
    return Response(status_code=204)


@router.get("/assignments/{assignment_id}/attempts", response_model=List[SubmissionHistoryItem])
def list_attempts(
    assignment_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    assignment = get_assignment_or_404(db, assignment_id)
    ensure_student_can_read_assignment_history(db, assignment, current_user)
    subs = (
        db.query(Submission)
        .filter(Submission.user_id == current_user.id, Submission.assignment_id == assignment_id)
        .order_by(Submission.attempt_number.asc())
        .all()
    )
    return [SubmissionHistoryItem.model_validate(hydrate_submission_from_normalized(db, s)) for s in subs]


@router.get(
    "/assignments/{assignment_id}/grade-history",
    response_model=List[StudentGradeHistoryItem],
)
def list_assignment_grade_history(
    assignment_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    assignment = get_assignment_or_404(db, assignment_id)
    ensure_student_can_read_assignment_history(db, assignment, current_user)
    rows = (
        db.query(SubmissionGradeRevision, Submission.attempt_number)
        .join(Submission, Submission.id == SubmissionGradeRevision.origin_submission_id)
        .filter(
            Submission.user_id == current_user.id,
            Submission.assignment_id == assignment_id,
            Submission.submitted_at.isnot(None),
        )
        .order_by(
            Submission.attempt_number.desc(),
            SubmissionGradeRevision.revision_number.desc(),
            SubmissionGradeRevision.id.desc(),
        )
        .all()
    )
    return [
        StudentGradeHistoryItem(
            submission_id=grade.origin_submission_id,
            attempt_number=attempt_number,
            **grade_student_history_payload(grade),
        )
        for grade, attempt_number in rows
    ]


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
def get_submission_detail(
    submission_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    sub = get_own_submission(db, submission_id, current_user.id)
    if sub.submitted_at is None:
        ensure_student_can_access_current_assignment(sub.assignment, current_user)
    hydrate_submission_from_normalized(db, sub)
    return SubmissionResponse.model_validate(sub)


@router.post("/assignments/{assignment_id}/start", response_model=SubmissionResponse)
def start_assignment(
    assignment_id: int,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found or inactive")
    ensure_student_is_in_assignment_scope(assignment, current_user)

    now = taipei_now()
    if assignment.start_date and now < assignment.start_date:
        raise HTTPException(status_code=403, detail="作業尚未開放，請等待開放日期後再試。")

    existing = (
        db.query(Submission)
        .filter(Submission.user_id == current_user.id, Submission.assignment_id == assignment_id)
        .order_by(Submission.attempt_number.desc())
        .with_for_update()
        .first()
    )

    if assignment.due_date and now > assignment.due_date:
        late = existing.late_deadline if existing else None
        if not late or now > late:
            raise HTTPException(status_code=403, detail="作業已截止，無法開始新的嘗試。")

    if existing and existing.submitted_at is None:
        hydrate_submission_from_normalized(db, existing)
        return SubmissionResponse.model_validate(existing)

    attempt = (existing.attempt_number + 1) if existing else 1
    if attempt > MAX_ATTEMPTS:
        raise HTTPException(
            status_code=400,
            detail=f"已達最多嘗試次數（{MAX_ATTEMPTS} 次）。Maximum attempts ({MAX_ATTEMPTS}) reached."
        )

    sub = Submission(
        user_id=current_user.id,
        assignment_id=assignment_id,
        question_set_key=assignment.question_set_key,
        attempt_number=attempt,
        stage=1,
        workflow_version=2,
        rubric_version_id=assignment.rubric_version_id,
    )
    db.add(sub)
    db.flush()
    replace_question_snapshot(
        db,
        sub,
        question_snapshot_for_attempt(assignment.questions),
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(Submission)
            .filter(Submission.user_id == current_user.id, Submission.assignment_id == assignment_id)
            .order_by(Submission.attempt_number.desc())
            .first()
        )
        if existing:
            hydrate_submission_from_normalized(db, existing)
            return SubmissionResponse.model_validate(existing)
        raise HTTPException(status_code=409, detail="請勿同時在多個裝置操作")
    db.refresh(sub)
    hydrate_submission_from_normalized(db, sub)
    return SubmissionResponse.model_validate(sub)


@router.post("/submissions/{submission_id}/draft1", response_model=SubmissionResponse)
async def save_draft1(
    submission_id: int,
    payload: Draft1AnswersRequest,
    current_user: User = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    sub = get_editable_submission_locked(db, submission_id, current_user.id)
    ensure_submission_stage(sub, {2, 3, 4}, "目前階段無法修改第一版草稿。")
    if not get_job_profile_data(db, sub):
        raise HTTPException(status_code=409, detail="請先完成欲應徵的職位資料")
    answers = bind_answers_to_snapshot(db, sub, payload.draft1_answers, require_all=False)
    for item in answers:
        validate_draft1_text(item["text"])
    lease = await acquire_operation_lock(submission_id, FEEDBACK_OPERATION)
    try:
        current_answers = list_answers(db, sub, "draft1")
        _apply_draft1_version_transition(sub, current_answers, answers)
        replace_answers(db, sub, "draft1", answers)
        db.commit()
        db.refresh(sub)
        hydrate_submission_from_normalized(db, sub)
        return SubmissionResponse.model_validate(sub)
    finally:
        await lease.release()
