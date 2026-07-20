import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_admin
from app.database import get_db
from app.db_helpers import load_users_by_ids
from app.models import (
    User, Assignment, Submission, ApiUsageLog, LoginEvent, ActiveSession,
    AdminAuditLog, WorkerRoutingEvent,
)
from app.services.admin_scope import (
    apply_student_visibility_filter, apply_user_visibility_filter,
    assignment_visible_to_admin, ensure_admin_can_access_user, is_privileged_admin,
)
from app.schemas import (
    ApiUsageLogResponse, ApiUsageLogListResponse,
    LoginEventResponse, LoginEventListResponse,
    ActiveSessionResponse,
    AdminAuditLogResponse, AdminAuditLogListResponse,
    WorkerRoutingStatusItem, WorkerRoutingStatusResponse, WorkerHealthResponse,
)
from app.utils import taipei_now
from app.config import settings
from app.services import worker_client
from app.services.workflow_policy import workflow_stage_label

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


ROUTE_STATUS_LABELS = {
    "worker_success": "台灣 worker",
    "fallback_error": "worker 失敗，已回主站",
    "local_weight": "本次留在主站",
    "local_cooldown": "worker 冷卻中",
    "local_disabled": "分流未啟用",
}


# ── Usage Logs ────────────────────────────────────────────────────────────────

@router.get("/usage-logs", response_model=ApiUsageLogListResponse)
def get_usage_logs(
    student_id: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    visible_user_ids = [
        user_id for user_id, in apply_user_visibility_filter(db.query(User.id), admin).all()
    ]
    if not visible_user_ids:
        return ApiUsageLogListResponse(total=0, logs=[])

    query = db.query(ApiUsageLog)

    if student_id:
        user = db.query(User).filter(User.student_id == student_id).first()
        if user:
            ensure_admin_can_access_user(admin, user)
            query = query.filter(ApiUsageLog.user_id == user.id)
        else:
            return ApiUsageLogListResponse(total=0, logs=[])
    else:
        query = query.filter(ApiUsageLog.user_id.in_(visible_user_ids))

    if date_from:
        query = query.filter(ApiUsageLog.called_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(ApiUsageLog.called_at <= datetime.combine(date_to, datetime.max.time()))

    total = query.count()
    logs = query.order_by(ApiUsageLog.called_at.desc()).offset(skip).limit(limit).all()

    log_users_by_id = load_users_by_ids(db, (log.user_id for log in logs))

    result = []
    for log in logs:
        user = log_users_by_id.get(log.user_id)
        result.append(ApiUsageLogResponse(
            id=log.id,
            user_id=log.user_id,
            student_id=user.student_id if user else None,
            name=user.name if user else None,
            stage=log.stage,
            called_at=log.called_at,
        ))
    return ApiUsageLogListResponse(total=total, logs=result)


@router.get("/login-events", response_model=LoginEventListResponse)
def list_login_events(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    student_id: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    visible_users = apply_user_visibility_filter(db.query(User), admin).all()
    visible_user_ids = [user.id for user in visible_users]
    if not visible_user_ids:
        return LoginEventListResponse(items=[], total=0, page=page, limit=limit)

    query = db.query(LoginEvent)

    if student_id:
        user = db.query(User).filter(User.student_id == student_id).first()
        if not user:
            return LoginEventListResponse(items=[], total=0, page=page, limit=limit)
        ensure_admin_can_access_user(admin, user)
        query = query.filter(LoginEvent.user_id == user.id)
    else:
        query = query.filter(LoginEvent.user_id.in_(visible_user_ids))
    if success is not None:
        query = query.filter(LoginEvent.success == success)
    if date_from:
        query = query.filter(LoginEvent.login_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(LoginEvent.login_at <= datetime.combine(date_to, datetime.max.time()))

    total = query.count()
    events = query.order_by(LoginEvent.login_at.desc()).offset((page - 1) * limit).limit(limit).all()

    event_users_by_id = load_users_by_ids(db, (ev.user_id for ev in events))

    items = []
    for ev in events:
        user = event_users_by_id.get(ev.user_id) if ev.user_id else None
        items.append(LoginEventResponse(
            id=ev.id,
            student_id=ev.student_id,
            name=user.name if user else None,
            ip_address=ev.ip_address,
            device_type=ev.device_type,
            success=ev.success,
            login_at=ev.login_at,
        ))
    return LoginEventListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/active-sessions", response_model=List[ActiveSessionResponse])
def list_active_sessions(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    now = taipei_now()
    visible_user_ids = [
        user_id for user_id, in apply_user_visibility_filter(db.query(User.id), admin).all()
    ]
    if not visible_user_ids:
        return []
    sessions = (
        db.query(ActiveSession)
        .filter(ActiveSession.expires_at > now, ActiveSession.user_id.in_(visible_user_ids))
        .order_by(ActiveSession.last_seen_at.desc())
        .all()
    )
    session_users_by_id = load_users_by_ids(db, (s.user_id for s in sessions))

    result = []
    for s in sessions:
        user = session_users_by_id.get(s.user_id)
        if not user:
            continue
        result.append(ActiveSessionResponse(
            id=s.id,
            user_id=s.user_id,
            student_id=user.student_id,
            name=user.name,
            role=user.role,
            ip_address=s.ip_address,
            device_type=s.device_type,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
        ))
    return result


@router.get("/worker-routing-status", response_model=WorkerRoutingStatusResponse)
def list_worker_routing_status(
    student_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    stage: Optional[int] = Query(None, ge=1, le=9),
    active_only: bool = Query(False),
    recent_minutes: int = Query(120, ge=5, le=1440),
    limit: int = Query(100, ge=1, le=300),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    now = taipei_now()
    visible_users = (
        apply_user_visibility_filter(db.query(User), admin)
        .filter(User.role == "student")
        .all()
    )
    if student_id:
        visible_users = [u for u in visible_users if u.student_id == student_id]
    visible_by_id = {u.id: u for u in visible_users}
    if not visible_by_id:
        return WorkerRoutingStatusResponse(
            enabled=settings.CHT_WORKER_ENABLED,
            base_url=settings.CHT_WORKER_BASE_URL,
            weight=settings.cht_worker_weight_ratio,
            cooldown_seconds=settings.CHT_WORKER_COOLDOWN_SECONDS,
            items=[],
        )

    visible_user_ids = set(visible_by_id)
    sessions = (
        db.query(ActiveSession)
        .filter(ActiveSession.expires_at > now, ActiveSession.user_id.in_(visible_user_ids))
        .order_by(ActiveSession.last_seen_at.desc())
        .all()
    )
    latest_session_by_user: dict[int, ActiveSession] = {}
    for session in sessions:
        latest_session_by_user.setdefault(session.user_id, session)

    visible_assignments = {
        assignment.id: assignment
        for assignment in db.query(Assignment).all()
        if assignment_visible_to_admin(admin, assignment)
    }
    visible_assignment_ids = set(visible_assignments)

    since = now - timedelta(minutes=recent_minutes)
    event_query = (
        db.query(WorkerRoutingEvent)
        .outerjoin(Submission, WorkerRoutingEvent.submission_id == Submission.id)
        .filter(
            WorkerRoutingEvent.user_id.in_(visible_user_ids),
            WorkerRoutingEvent.created_at >= since,
            or_(
                WorkerRoutingEvent.submission_id.is_(None),
                Submission.assignment_id.in_(visible_assignment_ids),
            ),
        )
        .order_by(WorkerRoutingEvent.created_at.desc(), WorkerRoutingEvent.id.desc())
    )
    if status:
        event_query = event_query.filter(WorkerRoutingEvent.route_status == status)
    events = event_query.limit(1000).all()
    latest_event_by_user: dict[int, WorkerRoutingEvent] = {}
    for event in events:
        if event.user_id is not None:
            latest_event_by_user.setdefault(event.user_id, event)

    candidate_user_ids = set(latest_session_by_user)
    if not active_only:
        candidate_user_ids.update(latest_event_by_user)
    candidate_user_ids.intersection_update(visible_user_ids)

    rows: list[WorkerRoutingStatusItem] = []
    for user_id in candidate_user_ids:
        user = visible_by_id.get(user_id)
        if not user:
            continue
        latest_submission = (
            db.query(Submission)
            .filter(
                Submission.user_id == user_id,
                Submission.assignment_id.in_(visible_assignment_ids),
            )
            .order_by(Submission.updated_at.desc(), Submission.id.desc())
            .first()
        ) if visible_assignment_ids else None
        if stage and (not latest_submission or latest_submission.stage != stage):
            continue
        event = latest_event_by_user.get(user_id)
        if status and not event:
            continue
        assignment = visible_assignments.get(latest_submission.assignment_id) if latest_submission else None
        session = latest_session_by_user.get(user_id)
        current_stage = latest_submission.stage if latest_submission else None
        rows.append(WorkerRoutingStatusItem(
            user_id=user.id,
            student_id=user.student_id,
            name=user.name,
            role=user.role,
            online=bool(session),
            last_seen_at=session.last_seen_at if session else None,
            submission_id=latest_submission.id if latest_submission else None,
            assignment_id=latest_submission.assignment_id if latest_submission else None,
            assignment_title=assignment.title if assignment else None,
            stage=current_stage,
            stage_label=workflow_stage_label(current_stage),
            operation=event.operation if event else None,
            route_status=event.route_status if event else None,
            route_status_label=ROUTE_STATUS_LABELS.get(event.route_status, event.route_status) if event else None,
            worker_url=event.worker_url if event else None,
            detail=event.detail if event else None,
            duration_ms=event.duration_ms if event else None,
            routed_at=event.created_at if event else None,
        ))

    rows.sort(key=lambda item: (
        0 if item.online else 1,
        -(item.routed_at.timestamp() if item.routed_at else 0),
        item.student_id,
    ))

    return WorkerRoutingStatusResponse(
        enabled=settings.CHT_WORKER_ENABLED,
        base_url=settings.CHT_WORKER_BASE_URL,
        weight=settings.cht_worker_weight_ratio,
        cooldown_seconds=settings.CHT_WORKER_COOLDOWN_SECONDS,
        items=rows[:limit],
    )


@router.get("/worker-health", response_model=WorkerHealthResponse)
async def get_worker_health(
    admin: User = Depends(get_current_admin),
):
    result = await worker_client.check_health()
    return WorkerHealthResponse(
        online=bool(result.get("online")),
        configured=bool(result.get("configured")),
        base_url=str(result.get("base_url") or ""),
        status_code=result.get("status_code"),
        duration_ms=result.get("duration_ms"),
        detail=result.get("detail"),
        checked_at=taipei_now(),
    )


@router.get("/admin-audit-logs", response_model=AdminAuditLogListResponse)
def list_admin_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    admin_student_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(AdminAuditLog)

    if not is_privileged_admin(admin):
        visible_student_ids = [
            str(row.id)
            for row in apply_student_visibility_filter(db.query(User), admin).all()
        ]
        query = query.filter(or_(
            AdminAuditLog.admin_student_id == admin.student_id,
            (
                AdminAuditLog.action.in_([
                    "student.password_reset.request",
                    "student.password_reset.confirm",
                ])
                & AdminAuditLog.target_id.in_(visible_student_ids)
            ),
        ))
    if admin_student_id:
        query = query.filter(AdminAuditLog.admin_student_id == admin_student_id)
    if action:
        query = query.filter(AdminAuditLog.action == action)
    if target_type:
        query = query.filter(AdminAuditLog.target_type == target_type)
    if date_from:
        query = query.filter(AdminAuditLog.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(AdminAuditLog.created_at <= datetime.combine(date_to, datetime.max.time()))

    total = query.count()
    logs = (
        query
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    items = [
        AdminAuditLogResponse(
            id=log.id,
            admin_user_id=log.admin_user_id,
            admin_student_id=log.admin_student_id,
            admin_name=log.admin_name,
            action=log.action,
            target_type=log.target_type,
            target_id=log.target_id,
            target_label=log.target_label,
            result=log.result,
            summary=log.summary,
            before_json=log.before_json,
            after_json=log.after_json,
            detail_json=log.detail_json,
            ip_address=log.ip_address,
            created_at=log.created_at,
        )
        for log in logs
    ]
    return AdminAuditLogListResponse(items=items, total=total, page=page, limit=limit)
