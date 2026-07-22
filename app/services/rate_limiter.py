from datetime import timedelta
from enum import IntEnum
from typing import Callable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ApiUsageLog, LoginEvent, User
from app.config import settings
from app.utils import taipei_now


class ExternalApiStage(IntEnum):
    JOB_PROFILE = 1
    WRITING_FEEDBACK = 3
    SHADOWING = 5
    ROLEPLAY = 6
    FINAL_REPORT = 7


def check_login_ip_rate_limit(db: Session, ip_address: str | None) -> None:
    """Raise HTTP 429 if a single source IP has too many failed logins recently.

    Complements per-account lockout (failed_login_count/locked_until) by blocking
    distributed brute-force / credential-stuffing that spreads across many accounts
    from one IP. Counts failed LoginEvent rows in the configured window.
    """
    if not ip_address:
        return
    window_start = taipei_now() - timedelta(minutes=settings.LOGIN_IP_WINDOW_MINUTES)
    failures = (
        db.query(LoginEvent)
        .filter(
            LoginEvent.ip_address == ip_address,
            LoginEvent.success.is_(False),
            LoginEvent.login_at >= window_start,
        )
        .count()
    )
    if failures >= settings.LOGIN_IP_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登入嘗試過於頻繁，請稍後再試。",
        )


def reserve_api_call(
    user_id: int,
    stage: ExternalApiStage,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """Atomically enforce and consume one external-API allowance.

    The dedicated transaction deliberately does not share the route's ORM
    session. Locking the user row serializes both the per-stage and aggregate
    daily counters across every web worker without committing caller state.
    """
    try:
        stage = ExternalApiStage(stage)
    except ValueError as exc:
        raise ValueError(f"Unsupported API usage stage: {stage}") from exc

    now = taipei_now()
    one_hour_ago = now - timedelta(hours=1)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with (session_factory or SessionLocal)() as quota_db:
        try:
            user = (
                quota_db.query(User)
                .filter(User.id == user_id)
                .with_for_update()
                .first()
            )
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="使用者不存在或已失效。",
                )

            hourly_count = (
                quota_db.query(ApiUsageLog)
                .filter(
                    ApiUsageLog.user_id == user_id,
                    ApiUsageLog.stage == stage,
                    ApiUsageLog.called_at >= one_hour_ago,
                )
                .count()
            )
            if hourly_count >= settings.STAGE_HOURLY_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: max {settings.STAGE_HOURLY_LIMIT} calls per hour for stage {stage}.",
                )

            daily_count = (
                quota_db.query(ApiUsageLog)
                .filter(
                    ApiUsageLog.user_id == user_id,
                    ApiUsageLog.called_at >= today_start,
                )
                .count()
            )
            if daily_count >= settings.DAILY_API_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Daily API limit exceeded: max {settings.DAILY_API_LIMIT} external API calls per day.",
                )

            quota_db.add(ApiUsageLog(user_id=user_id, stage=stage, called_at=now))
            quota_db.commit()
        except Exception:
            quota_db.rollback()
            raise
