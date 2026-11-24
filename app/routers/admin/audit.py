import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_admin
from app.database import get_db
from app.db_helpers import load_users_by_ids
from app.models import (
    User, ApiUsageLog, LoginEvent, ActiveSession,
    AdminAuditLog,
)
from app.services.admin_scope import (
    apply_student_visibility_filter, apply_user_visibility_filter,
    ensure_admin_can_access_user, ensure_privileged_admin, is_privileged_admin,
)
from app.schemas import (
    ApiUsageLogResponse, ApiUsageLogListResponse,
    LoginEventResponse, LoginEventListResponse,
    ActiveSessionResponse, LoginUnfreezeResponse,
    AdminAuditLogResponse, AdminAuditLogListResponse,
)
from app.utils import taipei_now
from app.services.admin_audit import log_admin_action
from app.services.rate_limiter import LOGIN_UNFREEZE_ACTION
from app.services.input_validator import normalize_http_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Usage Logs ────────────────────────────────────────────────────────────────

@router.get("/usage-logs", response_model=ApiUsageLogListResponse)
def get_usage_logs(
    student_id: Optional[str] = Query(None, max_length=64),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    student_id = normalize_http_text(student_id, field_name="student_id")
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
    student_id: Optional[str] = Query(None, max_length=64),
    success: Optional[bool] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    student_id = normalize_http_text(student_id, field_name="student_id")
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


@router.get("/admin-audit-logs", response_model=AdminAuditLogListResponse)
def list_admin_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    admin_student_id: Optional[str] = Query(None, max_length=64),
    action: Optional[str] = Query(None, max_length=64),
    target_type: Optional[str] = Query(None, max_length=32),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    admin_student_id = normalize_http_text(admin_student_id, field_name="admin_student_id")
    action = normalize_http_text(action, field_name="action")
    target_type = normalize_http_text(target_type, field_name="target_type")
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


@router.post("/login-unfreeze", response_model=LoginUnfreezeResponse)
def unfreeze_all_logins(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Clear every account lock and reset the per-IP failed-login window."""
    ensure_privileged_admin(admin, "只有指定管理員可解除全站登入限制")
    now = taipei_now()
    affected = (
        db.query(User)
        .filter(or_(User.locked_until.isnot(None), User.failed_login_count > 0))
        .with_for_update()
        .all()
    )
    locked = [u for u in affected if u.locked_until and u.locked_until > now]
    for user in affected:
        user.failed_login_count = 0
        user.locked_until = None
    log_admin_action(
        db,
        admin,
        LOGIN_UNFREEZE_ACTION,
        request=request,
        target_type="system",
        target_label="全站登入限制",
        summary=f"解除 {len(locked)} 個鎖定帳號，並重設 IP 登入失敗計數",
        details={
            "unlocked_student_ids": [u.student_id for u in locked][:200],
            "reset_failure_counts": len(affected),
        },
    )
    db.commit()
    if locked:
        message = f"已解除 {len(locked)} 個帳號的鎖定，IP 登入限制也一併重設。"
    else:
        message = "目前沒有被鎖定的帳號，IP 登入限制已重設。"
    return LoginUnfreezeResponse(
        unlocked_accounts=len(locked),
        reset_failure_counts=len(affected),
        message=message,
    )
