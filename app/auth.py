import hashlib
from datetime import timedelta
from typing import Optional

import jwt
from jwt.exceptions import InvalidTokenError
from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, ActiveSession
from app.services.legal_acknowledgement import requires_acknowledgement
from app.services.presence import touch_student_presence
from app.utils import get_client_ip, taipei_now

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_PASSWORD_CHANGE_ALLOWED_PATHS = {
    "/api/auth/me",
    "/api/auth/refresh",
    "/api/auth/logout",
    "/api/auth/change-password",
    "/api/auth/legal-acknowledgement",
}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = taipei_now() + (expires_delta or timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def prune_expired_sessions(db: Session, now=None) -> int:
    """Stage expired-session deletion in the caller's transaction."""
    now = now or taipei_now()
    deleted = (
        db.query(ActiveSession)
        .filter(ActiveSession.expires_at <= now)
        .delete(synchronize_session=False)
    )
    return deleted


def _refresh_session(db: Session, token: str, request: Request, user: "User") -> None:
    th = _token_hash(token)
    now = taipei_now()
    expire_hours = settings.ADMIN_TOKEN_EXPIRE_HOURS if user.role == "admin" else settings.ACCESS_TOKEN_EXPIRE_HOURS
    client_ip = get_client_ip(request)
    # Throttle the write: only touch the row once per SESSION_TOUCH_SECONDS window.
    # Outside that window the UPDATE matches 0 rows, so the vast majority of
    # requests incur no row write / WAL — avoiding a commit+fsync on every request.
    touch_before = now - timedelta(seconds=settings.SESSION_TOUCH_SECONDS)
    touched = db.query(ActiveSession).filter(
        ActiveSession.token_hash == th,
        ActiveSession.last_seen_at < touch_before,
    ).update({"last_seen_at": now, "ip_address": client_ip, "expires_at": now + timedelta(hours=expire_hours)})
    if touched and user.role != "admin":
        session = db.query(ActiveSession).filter(ActiveSession.token_hash == th).first()
        touch_student_presence(
            db,
            user_id=user.id,
            active_session_id=session.id if session else None,
            ip_address=client_ip,
            device_type=session.device_type if session else None,
            now=now,
        )
    db.commit()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="請再次登入",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    user_id: Optional[int] = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="請再次登入",
        )
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    # Use the ASGI router path instead of ``request.url.path``.  Older Starlette
    # releases could derive URL.path from an attacker-controlled Host header,
    # which made this security gate see a different path than the router.
    request_path = request.scope.get("path", "")
    if (
        user.must_change_password or requires_acknowledgement(user)
    ) and request_path not in _PASSWORD_CHANGE_ALLOWED_PATHS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="請先完成帳戶設定後再繼續使用。",
        )
    th = _token_hash(token)
    session = db.query(ActiveSession).filter(ActiveSession.token_hash == th).first()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session 已失效，請重新登入。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.role != "admin":
        token_version = payload.get("sv")
        if token_version is None or int(token_version) != user.session_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="已在其他裝置登入，請重新登入。",
                headers={"WWW-Authenticate": "Bearer"},
            )
    _refresh_session(db, token, request, user)
    return user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def get_current_student(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student access required",
        )
    return current_user


def verify_admin_password_or_raise(admin: User, password: str, action: str = "此操作") -> None:
    if not verify_password(password, admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"密碼錯誤，無法執行{action}",
        )
