import asyncio
import logging
from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, load_only

from app.auth import get_current_admin, verify_admin_password_or_raise
from app.database import get_db
from app.services import reminders
from app.db_helpers import get_assignment_or_404, get_latest_submission
from app.models import User, Assignment, Submission, Rubric, RubricVersion, SubmissionReflection
from app.schemas import (
    AssignmentCreate, AssignmentUpdate, AssignmentResponse,
    StudentResultItem,
    DeleteConfirmRequest, LateDeadlineRequest, BatchLateDeadlineRequest, SubmissionRewindRequest,
    SubmissionResponse,
    UserResponse,
)
from app.prompts import PRESET_ASSIGNMENTS
from app.question_sets import question_set_catalog
from app.services import mail
from app.services.admin_audit import log_admin_action, snapshot_assignment, snapshot_submission
from app.services.admin_scope import (
    apply_student_visibility_filter,
    assignment_visible_to_admin,
    ensure_admin_can_access_assignment,
    ensure_admin_can_mutate_assignment,
    ensure_admin_can_access_student_assignment,
    ensure_admin_can_assign_course_nums,
    ensure_privileged_admin,
    student_matches_assignment,
)
from app.services.submission_data import (
    get_report_data,
    hydrate_submission_from_normalized,
    question_snapshot_for_attempt,
    replace_question_snapshot,
)
from app.services.submission_rewind import REWINDABLE_STAGES, rewind_submission, rewind_summary
from app.services.grading import default_published_rubric_version, latest_grades_by_submission, grade_student_payload
from app.services.input_validator import normalize_http_text
from app.services.assignment_questions import (
    AssignmentQuestionPolicyError,
    apply_selection,
    selection_for_create,
    selection_for_preset_repair,
    selection_for_update,
)
from app.services.submission_assets import (
    enqueue_submission_asset_cleanup,
    list_submission_asset_refs,
    process_object_deletion_queue_async,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _get_accessible_assignment(db: Session, admin: User, assignment_id: int) -> Assignment:
    assignment = get_assignment_or_404(db, assignment_id)
    ensure_admin_can_access_assignment(admin, assignment)
    return assignment


def _get_mutable_assignment(db: Session, admin: User, assignment_id: int) -> Assignment:
    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id)
        .with_for_update()
        .first()
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    ensure_admin_can_mutate_assignment(admin, assignment)
    return assignment


def _get_visible_students_for_assignment(db: Session, admin: User, assignment: Assignment):
    students = apply_student_visibility_filter(
        db.query(User).options(load_only(User.id, User.student_id, User.name, User.email, User.course_num)),
        admin,
    ).filter(User.is_active == True).all()
    return [student for student in students if student_matches_assignment(student, assignment)]


def _published_rubric_id(db: Session, version_id: int | None) -> int:
    version = None
    if version_id is not None:
        version = (
            db.query(RubricVersion)
            .join(Rubric, Rubric.id == RubricVersion.rubric_id)
            .filter(
                RubricVersion.id == version_id,
                RubricVersion.status == "published",
                Rubric.is_archived == False,
            )
            .first()
        )
    else:
        version = default_published_rubric_version(db)
    if not version:
        raise HTTPException(status_code=400, detail="請選擇已發布的評分規準")
    return version.id


def _question_policy_or_400(callback, *args):
    try:
        return callback(*args)
    except AssignmentQuestionPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _get_or_create_late_deadline_submission(
    db: Session,
    assignment: Assignment,
    user_id: int,
):
    latest = get_latest_submission(db, user_id, assignment.id)
    before = snapshot_submission(latest)
    if latest:
        return latest, before

    latest = Submission(
        user_id=user_id,
        assignment_id=assignment.id,
        question_set_key=assignment.question_set_key,
        attempt_number=1,
        stage=1,
        workflow_version=2,
        rubric_version_id=assignment.rubric_version_id,
    )
    db.add(latest)
    db.flush()
    replace_question_snapshot(
        db,
        latest,
        question_snapshot_for_attempt(assignment.questions if assignment else None),
    )
    return latest, before


@router.post("/assignments/send-due-reminders")
async def send_due_reminders(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Manually trigger the same 72h-before-due reminder scan the scheduler runs.

    Counts who needs reminding up front (fast, DB-only) and sends in the background so
    the request doesn't block on SMTP. The dedup table makes this safe to click anytime.
    """
    ensure_privileged_admin(admin, "只有指定管理員可寄送截止提醒")
    targets = reminders.find_due_soon_targets(db)
    log_admin_action(
        db,
        admin,
        "admin.assignment.send_due_reminders",
        request=request,
        target_type="reminder_job",
        target_label="due-soon-reminders",
        summary=f"手動觸發到期提醒掃描，共 {len(targets)} 筆待寄送",
        details={"pending": len(targets)},
    )
    db.commit()
    if targets:
        asyncio.create_task(reminders.deliver_reminders(targets))
    return {"pending": len(targets), "message": f"找到 {len(targets)} 位待提醒學生，已在背景寄送。" if targets else "目前沒有需要提醒的學生（無 72 小時內截止且未完成的作業）。"}


@router.post("/assignments/seed-presets")
def seed_preset_assignments(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ensure_privileged_admin(admin, "只有指定管理員可同步預設作業")
    default_rubric_id = _published_rubric_id(db, None)

    created, updated, skipped = [], [], []
    for a_def in PRESET_ASSIGNMENTS:
        title = a_def["title"]
        question_set_key = a_def["question_set_key"]
        existing = db.query(Assignment).filter(Assignment.title == title).first()
        if existing:
            changed = False
            fields_to_sync = [
                ("description", a_def["description"]),
                ("prompt_context", a_def["prompt_context"]),
            ]
            for field, value in fields_to_sync:
                if getattr(existing, field) != value:
                    setattr(existing, field, value)
                    changed = True
            selection = selection_for_preset_repair(existing, question_set_key)
            changed = apply_selection(
                db,
                existing,
                selection,
                sync_attempts=True,
            ) or changed
            if changed:
                updated.append(title)
        else:
            selection = selection_for_create(
                AssignmentCreate(title=title, question_set_key=question_set_key)
            )
            assignment = Assignment(
                title=title,
                description=a_def["description"],
                prompt_context=a_def["prompt_context"],
                question_set_key=selection.question_set_key,
                questions=selection.questions,
                rubric_version_id=default_rubric_id,
                is_active=False,
            )
            db.add(assignment)
            created.append(title)

        if title not in created and title not in updated:
            skipped.append(title)

    log_admin_action(
        db,
        admin,
        "admin.assignment.seed_presets",
        request=request,
        target_type="assignment_batch",
        target_label="preset-assignments",
        summary=f"同步預設作業：新增 {len(created)} 筆、更新 {len(updated)} 筆、略過 {len(skipped)} 筆",
        details={"created": created, "updated": updated, "skipped": skipped},
    )
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


# ── Assignments CRUD ──────────────────────────────────────────────────────────

@router.get("/question-sets")
def list_question_sets(admin: User = Depends(get_current_admin)):
    return question_set_catalog()


@router.get("/assignments", response_model=List[AssignmentResponse])
def list_assignments(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    assignments = db.query(Assignment).order_by(Assignment.created_at.desc()).all()
    return [
        AssignmentResponse.model_validate(assignment)
        for assignment in assignments
        if assignment_visible_to_admin(admin, assignment)
    ]


@router.post("/assignments", response_model=AssignmentResponse, status_code=201)
def create_assignment(
    payload: AssignmentCreate,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    selection = _question_policy_or_400(selection_for_create, payload)
    a = Assignment(
        title=payload.title,
        description=payload.description,
        prompt_context=payload.prompt_context,
        question_set_key=selection.question_set_key,
        questions=selection.questions,
        course_nums=ensure_admin_can_assign_course_nums(admin, payload.course_nums),
        start_date=payload.start_date,
        due_date=payload.due_date,
        rubric_version_id=_published_rubric_id(db, payload.rubric_version_id),
        is_active=payload.is_active,
        created_by=admin.id,
    )
    db.add(a)
    db.flush()
    log_admin_action(
        db,
        admin,
        "admin.assignment.create",
        request=request,
        target_type="assignment",
        target_id=a.id,
        target_label=a.title,
        after=snapshot_assignment(a),
        summary=f"建立作業：{a.title}",
    )
    db.commit()
    db.refresh(a)
    return AssignmentResponse.model_validate(a)


@router.get("/assignments/{assignment_id}", response_model=AssignmentResponse)
def get_assignment(
    assignment_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    a = _get_accessible_assignment(db, admin, assignment_id)
    return AssignmentResponse.model_validate(a)


@router.put("/assignments/{assignment_id}", response_model=AssignmentResponse)
def update_assignment(
    assignment_id: int,
    payload: AssignmentUpdate,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    a = _get_mutable_assignment(db, admin, assignment_id)
    before = snapshot_assignment(a)
    # exclude_unset (not exclude_none) so that explicit nulls from the form —
    # e.g. clearing 開放日期/截止日期 or 課號限制 — are applied instead of silently dropped.
    update_data = payload.model_dump(exclude_unset=True)
    update_data.pop("question_set_key", None)
    update_data.pop("questions", None)
    selection = _question_policy_or_400(selection_for_update, a, payload)
    if "course_nums" in update_data:
        update_data["course_nums"] = ensure_admin_can_assign_course_nums(admin, payload.course_nums)
    if "rubric_version_id" in update_data:
        if payload.rubric_version_id == a.rubric_version_id:
            # Existing assignments may retain an archived rubric version. Only a
            # genuine reassignment must pass the active/published validation.
            update_data.pop("rubric_version_id")
        else:
            update_data["rubric_version_id"] = _published_rubric_id(db, payload.rubric_version_id)
    for field, value in update_data.items():
        setattr(a, field, value)
    if selection is not None:
        apply_selection(db, a, selection, sync_attempts=True)
    log_admin_action(
        db,
        admin,
        "admin.assignment.update",
        request=request,
        target_type="assignment",
        target_id=a.id,
        target_label=a.title,
        before=before,
        after=snapshot_assignment(a),
        summary=f"更新作業：{a.title}",
    )
    db.commit()
    db.refresh(a)
    return AssignmentResponse.model_validate(a)


@router.post("/assignments/{assignment_id}/delete", status_code=204)
def delete_assignment_confirmed(
    assignment_id: int,
    payload: DeleteConfirmRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    verify_admin_password_or_raise(admin, payload.admin_password, "刪除操作")
    a = _get_mutable_assignment(db, admin, assignment_id)
    asset_refs = list_submission_asset_refs(db, assignment_id=a.id)
    queued_prefixes = enqueue_submission_asset_cleanup(db, asset_refs)
    before = snapshot_assignment(a)
    logger.warning("Admin %s (id=%s) deleted assignment '%s' (id=%s)", admin.student_id, admin.id, a.title, a.id)
    log_admin_action(
        db,
        admin,
        "admin.assignment.delete",
        request=request,
        target_type="assignment",
        target_id=a.id,
        target_label=a.title,
        before=before,
        summary=f"刪除作業：{a.title}",
        details={"queued_object_prefixes": queued_prefixes},
    )
    db.delete(a)
    db.commit()
    background_tasks.add_task(process_object_deletion_queue_async)


@router.patch("/assignments/{assignment_id}/toggle", response_model=AssignmentResponse)
def toggle_assignment(
    assignment_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    a = _get_mutable_assignment(db, admin, assignment_id)
    before = snapshot_assignment(a)
    a.is_active = not a.is_active
    log_admin_action(
        db,
        admin,
        "admin.assignment.toggle",
        request=request,
        target_type="assignment",
        target_id=a.id,
        target_label=a.title,
        before=before,
        after=snapshot_assignment(a),
        summary=f"{'啟用' if a.is_active else '停用'}作業：{a.title}",
    )
    db.commit()
    db.refresh(a)
    return AssignmentResponse.model_validate(a)


# ── Results ───────────────────────────────────────────────────────────────────

@router.get("/assignments/{assignment_id}/results", response_model=List[StudentResultItem])
def list_results(
    assignment_id: int,
    course_num: Optional[str] = Query(None, max_length=64),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    course_num = normalize_http_text(course_num, field_name="course_num")
    assignment = _get_accessible_assignment(db, admin, assignment_id)
    students = _get_visible_students_for_assignment(db, admin, assignment)
    if course_num:
        students = [student for student in students if (student.course_num or "") == course_num]
    if not students:
        return []

    student_ids = [s.id for s in students]

    # Fetch all submissions for this assignment in one query. Workflow payloads live
    # in normalized child tables, so only stage/attempt/submitted/updated are loaded here.
    all_subs = (
        db.query(Submission)
        .filter(
            Submission.assignment_id == assignment_id,
            Submission.user_id.in_(student_ids),
        )
        .options(load_only(
            Submission.user_id,
            Submission.stage,
            Submission.attempt_number,
            Submission.submitted_at,
            Submission.updated_at,
            Submission.late_deadline,
        ))
        .order_by(Submission.user_id, Submission.attempt_number.desc())
        .all()
    )

    # Group by user_id
    subs_by_user: dict = defaultdict(list)
    for s in all_subs:
        subs_by_user[s.user_id].append(s)

    latest_ids = [rows[0].id for rows in subs_by_user.values() if rows]
    latest_grade_map = latest_grades_by_submission(db, latest_ids)
    issue_submission_ids = {
        row.submission_id
        for row in db.query(SubmissionReflection).filter(
            SubmissionReflection.submission_id.in_(latest_ids),
            SubmissionReflection.has_issue == True,
        ).all()
    } if latest_ids else set()

    result = []
    for student in students:
        subs = subs_by_user.get(student.id, [])
        if not subs:
            result.append(StudentResultItem(
                user_id=student.id,
                student_id=student.student_id,
                name=student.name,
                email=student.email,
                course_num=student.course_num,
                latest_stage=0,
                attempt_count=0,
                is_submitted=False,
                has_feedback=False,
                updated_at=None,
            ))
        else:
            latest = subs[0]
            latest_submitted = next((s for s in subs if s.submitted_at is not None), None)
            has_feedback = bool(latest_submitted and get_report_data(db, latest_submitted))
            grade = latest_grade_map.get(latest.id)
            result.append(StudentResultItem(
                user_id=student.id,
                student_id=student.student_id,
                name=student.name,
                email=student.email,
                course_num=student.course_num,
                latest_stage=latest.stage,
                attempt_count=len(subs),
                is_submitted=latest.submitted_at is not None,
                has_feedback=has_feedback,
                grading_status="graded" if grade else ("pending" if latest.submitted_at else "not_ready"),
                latest_final_score=float(grade.final_score) if grade else None,
                latest_grader_name=grade.grader_name if grade else None,
                latest_graded_at=grade.created_at if grade else None,
                has_issue=latest.id in issue_submission_ids,
                late_deadline=latest.late_deadline,
                updated_at=latest.updated_at,
            ))
    return result


@router.get("/assignments/{assignment_id}/students/{user_id}")
def get_student_detail(
    assignment_id: int,
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    assignment = _get_accessible_assignment(db, admin, assignment_id)
    student = db.query(User).filter(User.id == user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    ensure_admin_can_access_student_assignment(admin, student, assignment)
    subs = (
        db.query(Submission)
        .filter(
            Submission.user_id == user_id,
            Submission.assignment_id == assignment_id,
        )
        .order_by(Submission.attempt_number.asc())
        .all()
    )
    for sub in subs:
        hydrate_submission_from_normalized(db, sub)
    grades = latest_grades_by_submission(db, [sub.id for sub in subs])
    return {
        "student": UserResponse.model_validate(student),
        "assignment": AssignmentResponse.model_validate(assignment) if assignment else None,
        "submissions": [SubmissionResponse.model_validate(s) for s in subs],
        "latest_grades": {str(submission_id): grade_student_payload(row) for submission_id, row in grades.items()},
    }


@router.post("/assignments/{assignment_id}/students/{user_id}/retake", response_model=SubmissionResponse)
def allow_retake(
    assignment_id: int,
    user_id: int,
    payload: DeleteConfirmRequest,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    verify_admin_password_or_raise(admin, payload.admin_password, "允許重作操作")
    assignment = _get_accessible_assignment(db, admin, assignment_id)
    student = db.query(User).filter(User.id == user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    ensure_admin_can_access_student_assignment(admin, student, assignment)
    latest = get_latest_submission(db, user_id, assignment_id)
    attempt = (latest.attempt_number + 1) if latest else 1
    new_sub = Submission(
        user_id=user_id,
        assignment_id=assignment_id,
        question_set_key=assignment.question_set_key,
        attempt_number=attempt,
        stage=1,
        workflow_version=2,
        rubric_version_id=assignment.rubric_version_id,
    )
    db.add(new_sub)
    db.flush()
    replace_question_snapshot(
        db,
        new_sub,
        question_snapshot_for_attempt(assignment.questions if assignment else None),
    )
    log_admin_action(
        db,
        admin,
        "admin.assignment.allow_retake",
        request=request,
        target_type="submission",
        target_id=new_sub.id,
        target_label=f"assignment:{assignment_id}/user:{user_id}",
        after=snapshot_submission(new_sub),
        summary=f"允許學生重作作業，建立第 {attempt} 次提交",
        details={"assignment_id": assignment_id, "user_id": user_id},
    )
    db.commit()
    db.refresh(new_sub)
    hydrate_submission_from_normalized(db, new_sub)
    return SubmissionResponse.model_validate(new_sub)


@router.post(
    "/assignments/{assignment_id}/students/{user_id}/rewind",
    response_model=SubmissionResponse,
)
def rewind_student_submission(
    assignment_id: int,
    user_id: int,
    payload: SubmissionRewindRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Send the student's latest attempt back to an earlier stage."""
    verify_admin_password_or_raise(admin, payload.admin_password, "退回階段操作")
    if payload.target_stage not in REWINDABLE_STAGES:
        raise HTTPException(status_code=422, detail="這個階段不能作為重新開始的位置。")
    assignment = _get_accessible_assignment(db, admin, assignment_id)
    student = db.query(User).filter(User.id == user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    ensure_admin_can_access_student_assignment(admin, student, assignment)
    latest = get_latest_submission(db, user_id, assignment_id)
    if latest is None:
        raise HTTPException(status_code=404, detail="這位學生還沒有作答紀錄。")
    sub = (
        db.query(Submission)
        .filter(Submission.id == latest.id)
        .with_for_update()
        .first()
    )
    if payload.target_stage > sub.stage:
        raise HTTPException(status_code=409, detail="學生還沒做到這個階段，無法退回。")
    before = snapshot_submission(sub)
    result = rewind_submission(db, sub, payload.target_stage)
    summary = rewind_summary(result)
    log_admin_action(
        db,
        admin,
        "admin.assignment.rewind_submission",
        request=request,
        target_type="submission",
        target_id=sub.id,
        target_label=f"assignment:{assignment_id}/user:{user_id}",
        before=before,
        after=snapshot_submission(sub),
        summary=summary,
        details={
            "assignment_id": assignment_id,
            "user_id": user_id,
            "from_stage": result.from_stage,
            "to_stage": result.to_stage,
            "cleared": result.cleared,
            "queued_objects": result.queued_objects,
        },
    )
    db.commit()
    if result.queued_objects:
        background_tasks.add_task(process_object_deletion_queue_async)
    db.refresh(sub)
    hydrate_submission_from_normalized(db, sub)
    return SubmissionResponse.model_validate(sub)


@router.post("/assignments/{assignment_id}/students/{user_id}/late-deadline")
async def set_late_deadline(
    assignment_id: int,
    user_id: int,
    payload: LateDeadlineRequest,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    verify_admin_password_or_raise(admin, payload.admin_password, "設定補繳期限操作")
    assignment = _get_accessible_assignment(db, admin, assignment_id)
    student = db.query(User).filter(User.id == user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    ensure_admin_can_access_student_assignment(admin, student, assignment)
    latest, before = _get_or_create_late_deadline_submission(db, assignment, user_id)
    latest.late_deadline = payload.late_deadline
    log_admin_action(
        db,
        admin,
        "admin.assignment.set_late_deadline",
        request=request,
        target_type="submission",
        target_id=latest.id,
        target_label=f"assignment:{assignment_id}/user:{user_id}",
        before=before,
        after=snapshot_submission(latest),
        summary="設定學生補繳期限",
        details={"assignment_id": assignment_id, "user_id": user_id},
    )
    db.commit()
    email_sent = None
    if payload.late_deadline is not None:
        try:
            await mail.send_late_deadline_email(
                student.email,
                student.name,
                assignment.title,
                payload.late_deadline,
                student.backup_email,
            )
            email_sent = True
        except Exception:
            email_sent = False
            logger.exception(
                "Failed to send late-deadline email for assignment %s to user %s",
                assignment.id,
                student.id,
            )
    return {
        "ok": True,
        "late_deadline": payload.late_deadline,
        "email_sent": email_sent,
    }


@router.post("/assignments/{assignment_id}/students/late-deadline")
async def set_late_deadline_batch(
    assignment_id: int,
    payload: BatchLateDeadlineRequest,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    verify_admin_password_or_raise(admin, payload.admin_password, "批量設定補繳期限操作")
    assignment = _get_accessible_assignment(db, admin, assignment_id)

    students = db.query(User).filter(User.id.in_(payload.user_ids)).all()
    student_map = {student.id: student for student in students}
    missing_user_ids = [user_id for user_id in payload.user_ids if user_id not in student_map]
    if missing_user_ids:
        raise HTTPException(status_code=404, detail=f"找不到學生資料：{', '.join(map(str, missing_user_ids))}")

    created_submission_count = 0
    for user_id in payload.user_ids:
        student = student_map[user_id]
        ensure_admin_can_access_student_assignment(admin, student, assignment)
        latest, before = _get_or_create_late_deadline_submission(db, assignment, user_id)
        if before is None:
            created_submission_count += 1
        latest.late_deadline = payload.late_deadline

    log_admin_action(
        db,
        admin,
        "admin.assignment.set_late_deadline",
        request=request,
        target_type="assignment_batch",
        target_id=assignment.id,
        target_label=assignment.title,
        summary=f"批次設定 {len(payload.user_ids)} 位學生補繳期限",
        details={
            "assignment_id": assignment.id,
            "user_ids": payload.user_ids,
            "updated_count": len(payload.user_ids),
            "created_submission_count": created_submission_count,
            "late_deadline": payload.late_deadline,
        },
    )
    db.commit()
    email_failed_user_ids = []
    if payload.late_deadline is not None:
        for user_id in payload.user_ids:
            student = student_map[user_id]
            try:
                await mail.send_late_deadline_email(
                    student.email,
                    student.name,
                    assignment.title,
                    payload.late_deadline,
                    student.backup_email,
                )
            except Exception:
                email_failed_user_ids.append(user_id)
                logger.exception(
                    "Failed to send late-deadline email for assignment %s to user %s",
                    assignment.id,
                    user_id,
                )
    return {
        "ok": True,
        "updated_count": len(payload.user_ids),
        "created_submission_count": created_submission_count,
        "late_deadline": payload.late_deadline,
        "emails_sent": (
            len(payload.user_ids) - len(email_failed_user_ids)
            if payload.late_deadline is not None
            else 0
        ),
        "email_failed_user_ids": email_failed_user_ids,
    }
