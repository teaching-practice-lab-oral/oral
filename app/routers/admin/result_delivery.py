"""Admin APIs for generating and emailing complete student result packages."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_admin
from app.database import get_db
from app.db_helpers import get_assignment_or_404
from app.models import EmailJob, ResultPackage, User
from app.services.admin_audit import log_admin_action
from app.services.admin_scope import ensure_admin_can_access_assignment
from app.services.result_delivery import (
    ActiveResultDeliveryJob,
    create_result_delivery_job,
    result_delivery_job_payload,
    result_delivery_selection,
    run_result_delivery_job,
)
from app.utils import taipei_now


router = APIRouter(prefix="/api/admin", tags=["admin-result-delivery"])


def _assignment(db: Session, admin: User, assignment_id: int):
    assignment = get_assignment_or_404(db, assignment_id)
    ensure_admin_can_access_assignment(admin, assignment)
    return assignment


def _job(
    db: Session,
    assignment_id: int,
    job_id: str,
    *,
    lock: bool = False,
) -> EmailJob:
    query = (
        db.query(EmailJob)
        .filter(
            EmailJob.id == job_id,
            EmailJob.kind == "result_package",
            EmailJob.assignment_id == assignment_id,
        )
    )
    if lock:
        query = query.with_for_update()
    job = query.first()
    if job is None:
        raise HTTPException(status_code=404, detail="找不到成果寄送工作")
    return job


@router.get("/assignments/{assignment_id}/result-delivery/preview")
def preview_result_delivery(
    assignment_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    assignment = _assignment(db, admin, assignment_id)
    selection = result_delivery_selection(db, admin, assignment)
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
    return {
        "visible": selection["visible"],
        "eligible": selection["eligible_count"],
        "not_completed": selection["not_completed_count"],
        "not_graded": selection["not_graded_count"],
        "active_job_id": active.id if active else None,
    }


@router.post("/assignments/{assignment_id}/result-delivery")
async def start_result_delivery(
    assignment_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    assignment = _assignment(db, admin, assignment_id)
    try:
        job, selection = create_result_delivery_job(db, admin, assignment)
        log_admin_action(
            db,
            admin,
            "admin.assignment.send_result_packages",
            request=request,
            target_type="email_job",
            target_id=job.id,
            target_label=assignment.title,
            summary=f"啟動作業成果寄送，共 {job.total} 位學生",
            details={
                "assignment_id": assignment.id,
                "eligible": selection["eligible_count"],
                "not_completed": selection["not_completed_count"],
                "not_graded": selection["not_graded_count"],
            },
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ActiveResultDeliveryJob as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "這份作業已有成果寄送工作進行中",
                "job_id": exc.job_id,
            },
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        active = (
            db.query(EmailJob)
            .filter(
                EmailJob.kind == "result_package",
                EmailJob.assignment_id == assignment.id,
                EmailJob.state.in_(("queued", "running")),
            )
            .first()
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "這份作業已有成果寄送工作進行中",
                "job_id": active.id if active else None,
            },
        ) from exc

    asyncio.create_task(run_result_delivery_job(job.id))
    return result_delivery_job_payload(db, job)


@router.get("/assignments/{assignment_id}/result-delivery/latest")
def latest_result_delivery(
    assignment_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    assignment = _assignment(db, admin, assignment_id)
    job = (
        db.query(EmailJob)
        .filter(
            EmailJob.kind == "result_package",
            EmailJob.assignment_id == assignment.id,
        )
        .order_by(EmailJob.created_at.desc())
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="尚無成果寄送工作")
    payload = result_delivery_job_payload(db, job)
    db.rollback()
    return payload


@router.get("/assignments/{assignment_id}/result-delivery/{job_id}")
def get_result_delivery(
    assignment_id: int,
    job_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _assignment(db, admin, assignment_id)
    job = _job(db, assignment_id, job_id)
    payload = result_delivery_job_payload(db, job)
    db.rollback()
    return payload


@router.post("/assignments/{assignment_id}/result-delivery/{job_id}/retry")
async def retry_result_delivery(
    assignment_id: int,
    job_id: str,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    assignment = _assignment(db, admin, assignment_id)
    job = _job(db, assignment_id, job_id, lock=True)
    if job.state in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="成果寄送工作仍在進行中")
    retryable = (
        db.query(ResultPackage)
        .filter(
            ResultPackage.job_id == job.id,
            ResultPackage.state.in_(("partial", "failed")),
        )
        .count()
    )
    if not retryable:
        raise HTTPException(status_code=409, detail="沒有失敗項目需要重寄")
    other_active = (
        db.query(EmailJob)
        .filter(
            EmailJob.kind == "result_package",
            EmailJob.assignment_id == assignment.id,
            EmailJob.id != job.id,
            EmailJob.state.in_(("queued", "running")),
        )
        .first()
    )
    if other_active:
        raise HTTPException(status_code=409, detail="這份作業已有其他寄送工作進行中")

    job.state = "queued"
    job.error = None
    job.completed_at = None
    log_admin_action(
        db,
        admin,
        "admin.assignment.retry_result_packages",
        request=request,
        target_type="email_job",
        target_id=job.id,
        target_label=assignment.title,
        summary=f"重寄作業成果失敗項目，共 {retryable} 位學生",
        details={"assignment_id": assignment.id, "retryable": retryable},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="這份作業已有其他成果寄送工作進行中",
        ) from exc
    asyncio.create_task(run_result_delivery_job(job.id, retry_failed=True))
    return result_delivery_job_payload(db, job)
