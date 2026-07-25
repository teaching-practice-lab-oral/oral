"""Background creation and delivery of expiring student result packages."""

from __future__ import annotations

import asyncio
import base64
from datetime import timedelta
import hashlib
import hmac
import logging
import secrets
import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import (
    Assignment,
    EmailJob,
    ResultPackage,
    Submission,
    SubmissionGradeRevision,
    User,
)
from app.services import mail, storage
from app.services.admin_audit import log_admin_action
from app.services.admin_scope import (
    apply_student_visibility_filter,
    student_matches_assignment,
)
from app.services.assignment_grade_export import (
    _latest_submissions_by_user,
)
from app.services.export_builders import (
    build_submission_result_package,
    safe_export_name,
)
from app.services.grading import grade_admin_payload, latest_grades_by_submission
from app.services.submission_assets import enqueue_object_cleanup_at
from app.services.submission_data import hydrate_submission_from_normalized
from app.utils import taipei_now


logger = logging.getLogger(__name__)
_DELIVERY_CONCURRENCY = 2


class ActiveResultDeliveryJob(RuntimeError):
    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__("result delivery job is already active")


def result_download_token(package_id: str) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"student-result-package:{package_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def result_download_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def result_package_filename(
    student: User,
    assignment: Assignment,
    submission: Submission,
) -> str:
    title = safe_export_name(assignment.title, limit=70)
    student_id = safe_export_name(student.student_id, "student", 40)
    return f"{title}_{student_id}_第{submission.attempt_number}次_學習成果.zip"


def build_graded_submission_result_package(
    db: Session,
    student: User,
    assignment: Assignment,
    submission: Submission,
    grade: SubmissionGradeRevision,
) -> bytes:
    """Build the exact complete package shared by email and student download."""
    if submission.submitted_at is None:
        raise ValueError("作業尚未完成，無法匯出成果包")
    if submission.user_id != student.id or submission.assignment_id != assignment.id:
        raise ValueError("成果包來源資料不一致")
    if grade.origin_submission_id != submission.id:
        raise ValueError("批改版本與提交資料不一致")
    hydrate_submission_from_normalized(db, submission)
    setattr(submission, "latest_grade_data", grade_admin_payload(grade))
    return build_submission_result_package(student, assignment, submission)


def _visible_students(
    db: Session,
    admin: User,
    assignment: Assignment,
) -> list[User]:
    students = apply_student_visibility_filter(db.query(User), admin).all()
    return [
        student
        for student in students
        if student_matches_assignment(student, assignment)
    ]


def result_delivery_selection(
    db: Session,
    admin: User,
    assignment: Assignment,
) -> dict:
    students = _visible_students(db, admin, assignment)
    student_ids = [student.id for student in students]
    submissions = (
        db.query(Submission)
        .filter(
            Submission.assignment_id == assignment.id,
            Submission.user_id.in_(student_ids),
            Submission.submitted_at.isnot(None),
        )
        .order_by(
            Submission.user_id,
            Submission.attempt_number.desc(),
            Submission.id.desc(),
        )
        .all()
        if student_ids
        else []
    )
    latest_by_user = _latest_submissions_by_user(submissions)
    grades = latest_grades_by_submission(
        db,
        [submission.id for submission in latest_by_user.values()],
    )

    eligible = []
    not_completed = []
    not_graded = []
    for student in students:
        submission = latest_by_user.get(student.id)
        if submission is None:
            not_completed.append(student.id)
            continue
        grade = grades.get(submission.id)
        if grade is None:
            not_graded.append(student.id)
            continue
        eligible.append((student, submission, grade))
    return {
        "visible": len(students),
        "eligible": eligible,
        "eligible_count": len(eligible),
        "not_completed_count": len(not_completed),
        "not_graded_count": len(not_graded),
        "not_completed_user_ids": not_completed,
        "not_graded_user_ids": not_graded,
    }


def create_result_delivery_job(
    db: Session,
    admin: User,
    assignment: Assignment,
) -> tuple[EmailJob, dict]:
    active = (
        db.query(EmailJob)
        .filter(
            EmailJob.kind == "result_package",
            EmailJob.assignment_id == assignment.id,
            EmailJob.state.in_(("queued", "running")),
        )
        .order_by(EmailJob.created_at.desc())
        .first()
    )
    if active:
        raise ActiveResultDeliveryJob(active.id)

    selection = result_delivery_selection(db, admin, assignment)
    eligible = selection["eligible"]
    if not eligible:
        raise ValueError("目前沒有最新已完成且已批改的學生可寄送")

    job_id = uuid.uuid4().hex
    job = EmailJob(
        id=job_id,
        kind="result_package",
        assignment_id=assignment.id,
        created_by_id=admin.id,
        state="queued",
        total=len(eligible),
        details={
            "visible": selection["visible"],
            "eligible": selection["eligible_count"],
            "not_completed": selection["not_completed_count"],
            "not_graded": selection["not_graded_count"],
            "mailboxes_total": 0,
            "mailboxes_succeeded": 0,
            "mailboxes_failed": 0,
            "failures": [],
        },
    )
    db.add(job)

    mailboxes_total = 0
    for student, submission, grade in eligible:
        recipients = []
        primary_key = student.email.strip().casefold()
        for address in mail.student_recipients(student.email, student.backup_email):
            recipients.append(
                {
                    "kind": "primary" if address.strip().casefold() == primary_key else "backup",
                    "address": address,
                    "status": "pending",
                    "attempts": 0,
                    "error": None,
                }
            )
        mailboxes_total += len(recipients)
        db.add(
            ResultPackage(
                id=uuid.uuid4().hex,
                job_id=job_id,
                assignment_id=assignment.id,
                user_id=student.id,
                submission_id=submission.id,
                grade_revision_id=grade.id,
                student_id_snapshot=student.student_id,
                student_name_snapshot=student.name,
                assignment_title_snapshot=assignment.title,
                attempt_number=submission.attempt_number,
                filename=result_package_filename(student, assignment, submission),
                state="queued",
                recipients=recipients,
            )
        )
    job.details = {**job.details, "mailboxes_total": mailboxes_total}
    db.flush()
    return job, selection


def _build_package(package_id: str) -> None:
    with SessionLocal() as db:
        package = db.get(ResultPackage, package_id)
        if package is None:
            return
        now = taipei_now()
        if (
            package.object_key
            and package.expires_at
            and package.expires_at > now
            and package.token_hash
        ):
            package.state = "sending"
            db.commit()
            return
        package.state = "building"
        package.error = None
        db.commit()

        student = db.get(User, package.user_id) if package.user_id else None
        assignment = db.get(Assignment, package.assignment_id) if package.assignment_id else None
        submission = db.get(Submission, package.submission_id) if package.submission_id else None
        grade = db.get(SubmissionGradeRevision, package.grade_revision_id)
        if not student or not assignment or not submission or not grade:
            raise RuntimeError("成果包來源資料已不存在")
        payload = build_graded_submission_result_package(
            db,
            student,
            assignment,
            submission,
            grade,
        )
        token = result_download_token(package.id)
        token_hash = result_download_token_hash(token)
        expires_at = now + timedelta(days=settings.RESULT_PACKAGE_EXPIRE_DAYS)
        object_key = storage.object_key(
            "result-packages",
            package.id,
            f"{secrets.token_hex(16)}.zip",
        )
        storage.upload_file(object_key, payload, "application/zip")
        try:
            package.object_key = object_key
            package.token_hash = token_hash
            package.expires_at = expires_at
            package.state = "sending"
            enqueue_object_cleanup_at(db, object_key, expires_at)
            db.commit()
        except Exception:
            db.rollback()
            try:
                storage.delete_file(object_key)
            except Exception:
                logger.exception("Could not compensate uploaded result package %s", object_key)
            raise


def _mark_package_failed(package_id: str, exc: Exception) -> None:
    logger.error(
        "Result package build failed for id=%s",
        package_id,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    with SessionLocal() as db:
        package = db.get(ResultPackage, package_id)
        if package is not None:
            package.state = "failed"
            package.error = str(exc)[:500] or type(exc).__name__
            db.commit()


async def _deliver_package(package_id: str) -> None:
    try:
        await asyncio.to_thread(_build_package, package_id)
    except Exception as exc:
        _mark_package_failed(package_id, exc)
        return

    with SessionLocal() as db:
        package = db.get(ResultPackage, package_id)
        if package is None or not package.object_key or not package.expires_at:
            return
        pending = [
            item
            for item in (package.recipients or [])
            if item.get("status") != "sent"
        ]
        if not pending:
            package.state = "sent"
            package.error = None
            db.commit()
            return
        package.state = "sending"
        db.commit()
        recipients = [str(item["address"]) for item in pending]
        name = package.student_name_snapshot
        assignment_title = package.assignment_title_snapshot
        attempt_number = package.attempt_number
        expires_at = package.expires_at
        download_url = (
            f"{settings.PUBLIC_BASE_URL.rstrip('/')}/downloads/results/"
            f"{result_download_token(package.id)}"
        )

    try:
        delivery = await mail.send_result_package_email(
            recipients=recipients,
            name=name,
            assignment_title=assignment_title,
            attempt_number=attempt_number,
            download_url=download_url,
            expires_at=expires_at,
        )
    except Exception:
        logger.exception("Result email preparation failed for package id=%s", package_id)
        delivery = {address: False for address in recipients}

    with SessionLocal() as db:
        package = db.get(ResultPackage, package_id)
        if package is None:
            return
        updated, state, error = apply_recipient_delivery(
            package.recipients or [],
            delivery,
        )
        package.recipients = updated
        package.state = state
        package.error = error
        db.commit()


def apply_recipient_delivery(
    recipients: list[dict],
    delivery: dict[str, bool],
) -> tuple[list[dict], str, str | None]:
    """Apply one delivery attempt while preserving already successful mailboxes."""
    updated = []
    for item in recipients:
        result = dict(item)
        address = str(result.get("address") or "")
        if address in delivery:
            result["attempts"] = int(result.get("attempts") or 0) + 1
            result["status"] = "sent" if delivery[address] else "failed"
            result["error"] = None if delivery[address] else "SMTP 寄送失敗"
        updated.append(result)
    sent_count = sum(item.get("status") == "sent" for item in updated)
    failed_count = sum(item.get("status") == "failed" for item in updated)
    if updated and sent_count == len(updated):
        return updated, "sent", None
    if sent_count:
        return updated, "partial", f"{failed_count} 個信箱寄送失敗"
    return updated, "failed", "所有信箱皆寄送失敗"


def _refresh_job_progress(db: Session, job: EmailJob) -> None:
    packages = (
        db.query(ResultPackage)
        .filter(ResultPackage.job_id == job.id)
        .order_by(ResultPackage.student_id_snapshot)
        .all()
    )
    terminal = {"sent", "partial", "failed", "expired"}
    processed = sum(package.state in terminal for package in packages)
    succeeded = sum(package.state == "sent" for package in packages)
    failed = sum(package.state in {"partial", "failed", "expired"} for package in packages)
    mailbox_total = 0
    mailbox_succeeded = 0
    mailbox_failed = 0
    failures = []
    package_states = {
        state: sum(package.state == state for package in packages)
        for state in (
            "queued",
            "building",
            "sending",
            "sent",
            "partial",
            "failed",
            "expired",
        )
    }
    for package in packages:
        recipients = package.recipients or []
        mailbox_total += len(recipients)
        mailbox_succeeded += sum(item.get("status") == "sent" for item in recipients)
        mailbox_failed += sum(item.get("status") == "failed" for item in recipients)
        if package.state in {"partial", "failed", "expired"}:
            failures.append(
                {
                    "student_id": package.student_id_snapshot,
                    "name": package.student_name_snapshot,
                    "state": package.state,
                    "error": package.error or "成果寄送失敗",
                    "failed_addresses": [
                        item.get("address")
                        for item in recipients
                        if item.get("status") == "failed"
                    ],
                }
            )
    job.processed = processed
    job.succeeded = succeeded
    job.failed = failed
    job.details = {
        **(job.details or {}),
        "mailboxes_total": mailbox_total,
        "mailboxes_succeeded": mailbox_succeeded,
        "mailboxes_failed": mailbox_failed,
        "package_states": package_states,
        "failures": failures,
    }


def _log_job_completion(db: Session, job: EmailJob) -> None:
    admin = db.get(User, job.created_by_id) if job.created_by_id else None
    if admin is None:
        return
    packages = (
        db.query(ResultPackage)
        .filter(ResultPackage.job_id == job.id)
        .order_by(ResultPackage.student_id_snapshot)
        .all()
    )
    log_admin_action(
        db,
        admin,
        "admin.assignment.result_packages_completed",
        target_type="email_job",
        target_id=job.id,
        target_label=packages[0].assignment_title_snapshot if packages else None,
        result="failure" if job.state == "failed" else "success",
        summary=(
            f"成果寄送完成：{job.succeeded} 位成功，"
            f"{job.failed} 位部分成功或失敗"
        ),
        details={
            "assignment_id": job.assignment_id,
            "students": job.total,
            "state": job.state,
            "mailboxes": [
                {
                    "student_id": package.student_id_snapshot,
                    "state": package.state,
                    "recipients": [
                        {
                            "kind": recipient.get("kind"),
                            "address": recipient.get("address"),
                            "status": recipient.get("status"),
                            "attempts": recipient.get("attempts"),
                            "error": recipient.get("error"),
                        }
                        for recipient in (package.recipients or [])
                    ],
                    "error": package.error,
                }
                for package in packages
            ],
        },
    )


async def run_result_delivery_job(job_id: str, *, retry_failed: bool = False) -> None:
    with SessionLocal() as db:
        job = db.get(EmailJob, job_id)
        if job is None or job.kind != "result_package":
            return
        job.state = "running"
        job.error = None
        job.completed_at = None
        packages = (
            db.query(ResultPackage)
            .filter(ResultPackage.job_id == job_id)
            .order_by(ResultPackage.student_id_snapshot)
            .all()
        )
        if retry_failed:
            package_ids = [
                package.id
                for package in packages
                if package.state in {"partial", "failed"}
            ]
        else:
            package_ids = [package.id for package in packages]
        db.commit()

    semaphore = asyncio.Semaphore(_DELIVERY_CONCURRENCY)

    async def run_one(package_id: str) -> None:
        async with semaphore:
            await _deliver_package(package_id)
            with SessionLocal() as progress_db:
                progress_job = progress_db.get(EmailJob, job_id)
                if progress_job is not None:
                    _refresh_job_progress(progress_db, progress_job)
                    progress_db.commit()

    try:
        await asyncio.gather(*(run_one(package_id) for package_id in package_ids))
        with SessionLocal() as db:
            job = db.get(EmailJob, job_id)
            if job is not None:
                _refresh_job_progress(db, job)
                job.state = "completed"
                job.completed_at = taipei_now()
                _log_job_completion(db, job)
                db.commit()
    except Exception as exc:
        logger.exception("Result delivery job %s crashed", job_id)
        with SessionLocal() as db:
            job = db.get(EmailJob, job_id)
            if job is not None:
                _refresh_job_progress(db, job)
                job.state = "failed"
                job.error = str(exc)[:500] or type(exc).__name__
                job.completed_at = taipei_now()
                _log_job_completion(db, job)
                db.commit()


def result_delivery_job_payload(db: Session, job: EmailJob) -> dict:
    _refresh_job_progress(db, job)
    return {
        "job_id": job.id,
        "assignment_id": job.assignment_id,
        "state": job.state,
        "total": job.total,
        "processed": job.processed,
        "succeeded": job.succeeded,
        "failed": job.failed,
        "details": job.details or {},
        "error": job.error,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }
