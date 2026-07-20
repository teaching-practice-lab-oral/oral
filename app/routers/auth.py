import logging
import secrets
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
import httpx

from app.auth import (
    verify_password, hash_password, create_access_token, get_current_user, _token_hash,
    decode_token, prune_expired_sessions,
)
from app.config import settings
from app.database import get_db
from app.models import User, LoginEvent, ActiveSession, PasswordResetToken, StudentPresence
from app.services.presence import acquire_student_presence, release_student_presence
from app.schemas import (
    ChangePasswordRequest, MessageResponse,
    LoginRequest, LoginResponse, PasswordResetConfirm, PasswordResetRequestCreate,
    UserMe,
)
from app.services import mail
from app.services.admin_audit import log_actor_action
from app.services.rate_limiter import check_login_ip_rate_limit
from app.utils import get_client_ip, taipei_now

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

_COOKIE_NAME = "access_token"
_RESET_REQUEST_RESPONSE = {
    "message": "若資料與系統紀錄相符，密碼重設連結將寄至可用信箱，請檢查收件匣與垃圾郵件匣。"
}


def _record_password_reset_audit(
    db: Session,
    request: Request | None,
    *,
    action: str,
    result: str,
    reason: str,
    student_id: str,
    name: str | None = None,
    course_num: str | None = None,
    backup_email: str | None = None,
    user: User | None = None,
    commit: bool = True,
):
    operation = "申請密碼重設" if action.endswith(".request") else "設定新密碼"
    entry = log_actor_action(
        db,
        action,
        actor_student_id=student_id or "未識別",
        actor_name=name,
        actor_user=user,
        request=request,
        target_type="user",
        target_id=user.id if user else None,
        target_label=user.student_id if user else (student_id or "未識別"),
        summary=f"學生{operation}：{student_id or '未識別'}",
        details={
            "reason": reason,
            "submitted_course_num": course_num,
            "submitted_backup_email": backup_email,
        },
        result=result,
    )
    if commit:
        db.commit()
    return entry


def _parse_device_type(user_agent: str | None) -> str:
    if not user_agent:
        return "unknown"
    ua = user_agent.lower()
    # Tablet: iPad, or Android without "mobile" (Android tablets omit "Mobile" token)
    if "ipad" in ua or ("android" in ua and "mobile" not in ua):
        return "tablet"
    # Mobile: explicit mobile tokens, Android phone (android + mobile), iOS devices
    if any(k in ua for k in ["mobile", "iphone", "ipod", "windows phone", "blackberry"]):
        return "mobile"
    return "desktop"


def _record_login(
    db: Session,
    student_id: str,
    success: bool,
    ip_address: str | None,
    user_agent: str | None,
    user_id: int | None = None,
) -> None:
    event = LoginEvent(
        user_id=user_id,
        student_id=student_id,
        ip_address=ip_address,
        user_agent=user_agent,
        device_type=_parse_device_type(user_agent),
        success=success,
    )
    db.add(event)
    db.commit()


async def _verify_turnstile(token: str, remote_ip: str | None) -> bool:
    """Return True if Turnstile token is valid."""
    if not settings.TURNSTILE_SECRET_KEY:
        if settings.APP_ENV == "production":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="伺服器安全設定錯誤，請聯繫管理員。",
            )
        return True
    data = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=data,
        )
        return res.json().get("success", False)


@router.post("/password-reset/request")
async def request_password_reset(
    payload: PasswordResetRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    client_ip = get_client_ip(request)
    requested_backup = str(payload.backup_email).strip() if payload.backup_email else None
    try:
        turnstile_valid = await _verify_turnstile(payload.turnstile_token, client_ip)
    except Exception:
        _record_password_reset_audit(
            db, request,
            action="student.password_reset.request", result="failure",
            reason="turnstile_service_error", student_id=payload.student_id,
            name=payload.name, course_num=payload.course_num, backup_email=requested_backup,
        )
        raise
    if not turnstile_valid:
        _record_password_reset_audit(
            db, request,
            action="student.password_reset.request", result="failure",
            reason="turnstile_failed", student_id=payload.student_id,
            name=payload.name, course_num=payload.course_num, backup_email=requested_backup,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="人機驗證失敗，請重新整理頁面後再試。",
        )

    user = db.query(User).filter(User.student_id == payload.student_id).with_for_update().first()
    if not (
        user
        and user.role == "student"
        and user.is_active
        and (user.course_num or "").strip() == payload.course_num
        and user.name.strip() == payload.name
    ):
        _record_password_reset_audit(
            db, request,
            action="student.password_reset.request", result="failure",
            reason="identity_mismatch", student_id=payload.student_id,
            name=payload.name, course_num=payload.course_num, backup_email=requested_backup,
            user=user,
        )
        return _RESET_REQUEST_RESPONSE

    stored_backup = (user.backup_email or "").strip()
    if requested_backup and stored_backup and requested_backup.casefold() != stored_backup.casefold():
        _record_password_reset_audit(
            db, request,
            action="student.password_reset.request", result="failure",
            reason="backup_email_mismatch", student_id=payload.student_id,
            name=payload.name, course_num=payload.course_num, backup_email=requested_backup,
            user=user,
        )
        return _RESET_REQUEST_RESPONSE

    now = taipei_now()
    user_cutoff = now - timedelta(hours=24)
    if db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.created_at >= user_cutoff,
    ).count() >= settings.PASSWORD_RESET_USER_DAILY_LIMIT:
        _record_password_reset_audit(
            db, request,
            action="student.password_reset.request", result="failure",
            reason="student_daily_limit", student_id=payload.student_id,
            name=payload.name, course_num=payload.course_num, backup_email=requested_backup,
            user=user,
        )
        return _RESET_REQUEST_RESPONSE
    if client_ip and db.query(PasswordResetToken).filter(
        PasswordResetToken.request_ip == client_ip,
        PasswordResetToken.created_at >= now - timedelta(hours=1),
    ).count() >= settings.PASSWORD_RESET_IP_HOURLY_LIMIT:
        _record_password_reset_audit(
            db, request,
            action="student.password_reset.request", result="failure",
            reason="ip_hourly_limit", student_id=payload.student_id,
            name=payload.name, course_num=payload.course_num, backup_email=requested_backup,
            user=user,
        )
        return _RESET_REQUEST_RESPONSE

    raw_token = secrets.token_urlsafe(32)
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=_token_hash(raw_token),
        request_ip=client_ip,
        created_at=now,
        expires_at=now + timedelta(hours=settings.PASSWORD_RESET_EXPIRE_HOURS),
    )
    db.add(reset_token)
    audit_entry = _record_password_reset_audit(
        db, request,
        action="student.password_reset.request", result="success",
        reason="reset_link_created", student_id=user.student_id,
        name=user.name, course_num=user.course_num, backup_email=requested_backup,
        user=user, commit=False,
    )
    db.commit()

    reset_url = (
        f"{settings.PUBLIC_BASE_URL.rstrip('/')}/reset-password?token="
        f"{quote(raw_token, safe='')}"
    )
    recipients = [(user.email, True)]
    # A reset token may only go to addresses already associated with the account.
    # The request form's backup address is untrusted input: when no backup is
    # registered it is included only in the admin notice, never as a recipient.
    backup_candidates = [user.backup_email]
    seen_recipients = {user.email.strip().casefold()}
    for backup_candidate in backup_candidates:
        normalized = (backup_candidate or "").strip()
        if normalized and normalized.casefold() not in seen_recipients:
            recipients.append((normalized, False))
            seen_recipients.add(normalized.casefold())
    delivery_results = []
    for recipient, is_system_email in recipients:
        try:
            await mail.send_password_reset_link(
                recipient,
                user.name,
                reset_url,
                requested_backup,
                is_system_email,
            )
            delivery_results.append({"recipient": recipient, "sent": True})
        except Exception:
            delivery_results.append({"recipient": recipient, "sent": False})
            logger.exception(
                "Failed to send self-service password reset link to user id=%s recipient=%s",
                user.id,
                recipient,
            )
    admin_notice_sent = True
    try:
        await mail.send_password_reset_admin_notice(
            user.name,
            user.student_id,
            user.course_num or "",
            now,
            requested_backup,
        )
    except Exception:
        admin_notice_sent = False
        logger.exception("Failed to send password-reset admin notice for user id=%s", user.id)
    link_delivered = any(item["sent"] for item in delivery_results)
    audit_entry.result = "success" if link_delivered else "failure"
    audit_entry.detail_json = {
        **(audit_entry.detail_json or {}),
        "reason": "reset_link_sent" if link_delivered else "email_delivery_failed",
        "email_delivery": delivery_results,
        "admin_notice_sent": admin_notice_sent,
    }
    db.commit()
    return _RESET_REQUEST_RESPONSE


@router.post("/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirm,
    request: Request,
    db: Session = Depends(get_db),
):
    now = taipei_now()
    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == _token_hash(payload.token),
    ).with_for_update().first()
    audit_user = db.query(User).filter(User.id == reset_token.user_id).first() if reset_token else None
    if not reset_token or reset_token.used_at is not None or reset_token.expires_at <= now:
        reason = "token_not_found"
        if reset_token and reset_token.used_at is not None:
            reason = "token_already_used"
        elif reset_token and reset_token.expires_at <= now:
            reason = "token_expired"
        _record_password_reset_audit(
            db, request,
            action="student.password_reset.confirm", result="failure", reason=reason,
            student_id=audit_user.student_id if audit_user else "未識別",
            name=audit_user.name if audit_user else None,
            course_num=audit_user.course_num if audit_user else None,
            user=audit_user,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="重設連結無效、已使用或已過期，請重新申請。",
        )
    user = db.query(User).filter(User.id == reset_token.user_id).with_for_update().first()
    if not user or not user.is_active or user.role != "student":
        _record_password_reset_audit(
            db, request,
            action="student.password_reset.confirm", result="failure",
            reason="user_inactive_or_not_student",
            student_id=user.student_id if user else "未識別",
            name=user.name if user else None,
            course_num=user.course_num if user else None,
            user=user,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="重設連結無效、已使用或已過期，請重新申請。",
        )

    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    user.failed_login_count = 0
    user.locked_until = None
    user.session_version = (user.session_version or 0) + 1
    reset_token.used_at = now
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.id != reset_token.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    db.query(ActiveSession).filter(ActiveSession.user_id == user.id).delete(synchronize_session=False)
    db.query(StudentPresence).filter(StudentPresence.user_id == user.id).delete(synchronize_session=False)
    _record_password_reset_audit(
        db, request,
        action="student.password_reset.confirm", result="success",
        reason="password_changed", student_id=user.student_id,
        name=user.name, course_num=user.course_num, user=user, commit=False,
    )
    db.commit()
    return {"message": "密碼已重設，請使用新密碼登入。"}


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    # Turnstile verification
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")
    # Per-IP brute-force throttle (complements per-account lockout below)
    check_login_ip_rate_limit(db, client_ip)
    db.rollback()
    if not await _verify_turnstile(payload.turnstile_token, client_ip):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="人機驗證失敗，請重新整理頁面後再試。",
        )

    # Serialize password/account state and student session rotation. Without this
    # row lock, concurrent logins can both issue the same session_version.
    user = (
        db.query(User)
        .filter(User.student_id == payload.student_id)
        .with_for_update()
        .first()
    )

    if user and user.locked_until and user.locked_until > taipei_now():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="帳號已暫時鎖定，請 15 分鐘後再試。",
        )

    if not user or not verify_password(payload.password, user.hashed_password):
        if user:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= 5:
                user.locked_until = taipei_now() + timedelta(minutes=15)
            db.commit()
        _record_login(db, payload.student_id, False, client_ip, user_agent, user.id if user else None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="學號或密碼錯誤。",
        )
    if not user.is_active:
        _record_login(db, payload.student_id, False, client_ip, user_agent, user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="帳號已停用，請聯繫管理員。",
        )

    user.failed_login_count = 0
    user.locked_until = None

    token_data: dict = {"sub": str(user.id), "role": user.role}
    expires = timedelta(hours=settings.ADMIN_TOKEN_EXPIRE_HOURS if user.role == "admin" else settings.ACCESS_TOKEN_EXPIRE_HOURS)
    if user.role != "admin":
        user.session_version = (user.session_version or 0) + 1
        token_data["sv"] = user.session_version
    token = create_access_token(token_data, expires_delta=expires)

    prune_expired_sessions(db)

    # Clean up old sessions for non-admin users (single-device)
    if user.role != "admin":
        db.query(ActiveSession).filter(ActiveSession.user_id == user.id).delete()
        release_student_presence(db, user_id=user.id)

    session = ActiveSession(
        token_hash=_token_hash(token),
        user_id=user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        device_type=_parse_device_type(user_agent),
        expires_at=taipei_now() + expires,
    )
    db.add(session)
    db.flush()
    if user.role != "admin":
        acquire_student_presence(
            db,
            user_id=user.id,
            active_session_id=session.id,
            ip_address=client_ip,
            device_type=session.device_type,
        )
    db.commit()

    _record_login(db, payload.student_id, True, client_ip, user_agent, user.id)

    is_secure = settings.APP_ENV == "production"
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        max_age=int(expires.total_seconds()),
        path="/",
    )
    return LoginResponse(
        role=user.role,
        name=user.name,
        user_id=user.id,
        must_change_password=bool(user.must_change_password),
        is_privileged_admin=bool(user.is_privileged_admin),
    )


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change credentials for either authenticated role at the auth boundary."""
    if not verify_password(payload.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="舊密碼不正確")
    current_user.hashed_password = hash_password(payload.new_password)
    current_user.must_change_password = False
    if current_user.role != "admin":
        current_user.session_version = (current_user.session_version or 0) + 1

    expires = timedelta(
        hours=settings.ADMIN_TOKEN_EXPIRE_HOURS
        if current_user.role == "admin"
        else settings.ACCESS_TOKEN_EXPIRE_HOURS
    )
    token_data: dict = {"sub": str(current_user.id), "role": current_user.role}
    if current_user.role != "admin":
        token_data["sv"] = current_user.session_version
    new_token = create_access_token(token_data, expires_delta=expires)

    db.query(ActiveSession).filter(ActiveSession.user_id == current_user.id).delete()
    active_session = ActiveSession(
        token_hash=_token_hash(new_token),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
        device_type=_parse_device_type(request.headers.get("User-Agent")),
        expires_at=taipei_now() + expires,
    )
    db.add(active_session)
    db.flush()
    if current_user.role != "admin":
        acquire_student_presence(
            db,
            user_id=current_user.id,
            active_session_id=active_session.id,
            ip_address=active_session.ip_address,
            device_type=active_session.device_type,
        )
    db.commit()
    response.set_cookie(
        key=_COOKIE_NAME,
        value=new_token,
        httponly=True,
        samesite="lax",
        secure=settings.APP_ENV == "production",
        max_age=int(expires.total_seconds()),
        path="/",
    )
    return MessageResponse(message="密碼已成功更新")


@router.post("/refresh")
def refresh_session(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登入")
    payload = decode_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="請再次登入")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="請再次登入")
    if user.role != "admin":
        token_version = payload.get("sv")
        if token_version is None or int(token_version) != user.session_version:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="已在其他裝置登入，請重新登入。")
    th = _token_hash(token)
    prune_expired_sessions(db)
    session = db.query(ActiveSession).filter(ActiveSession.token_hash == th).first()
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session 已失效，請重新登入。")
    expires = timedelta(hours=settings.ADMIN_TOKEN_EXPIRE_HOURS if user.role == "admin" else settings.ACCESS_TOKEN_EXPIRE_HOURS)
    token_data: dict = {"sub": str(user.id), "role": user.role}
    if user.role != "admin":
        token_data["sv"] = user.session_version
    new_token = create_access_token(token_data, expires_delta=expires)
    new_th = _token_hash(new_token)
    now = taipei_now()
    session.token_hash = new_th
    session.expires_at = now + expires
    session.last_seen_at = now
    if user.role != "admin":
        # Every auth mutation must lock ActiveSession before StudentPresence.
        # Ordinary authenticated requests use that order in app.auth; flushing
        # here prevents SQLAlchemy from deferring this UPDATE until after the
        # presence row has been locked, which can deadlock across browser tabs.
        db.flush()
        acquire_student_presence(
            db,
            user_id=user.id,
            active_session_id=session.id,
            ip_address=get_client_ip(request),
            device_type=session.device_type,
            now=now,
        )
    db.commit()
    is_secure = settings.APP_ENV == "production"
    response.set_cookie(
        key=_COOKIE_NAME,
        value=new_token,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        max_age=int(expires.total_seconds()),
        path="/",
    )
    return {"ok": True, "role": user.role, "name": user.name}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(_COOKIE_NAME)
    if token:
        user_id = None
        user = None
        try:
            payload = decode_token(token)
            user_id = payload.get("sub")
            if user_id:
                user = db.query(User).filter(User.id == int(user_id)).first()
                if user and user.role != "admin":
                    user.session_version = (user.session_version or 0) + 1
        except Exception:
            pass
        db.query(ActiveSession).filter(ActiveSession.token_hash == _token_hash(token)).delete()
        if user_id and user and user.role != "admin":
            release_student_presence(db, user_id=user.id)
        db.commit()
    response.delete_cookie(key=_COOKIE_NAME, path="/")
    return {"message": "登出成功"}


@router.get("/me", response_model=UserMe)
def me(current_user: User = Depends(get_current_user)):
    return current_user
