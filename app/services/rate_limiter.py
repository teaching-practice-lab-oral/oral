from datetime import timedelta
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import ApiUsageLog, LoginEvent
from app.config import settings
from app.utils import taipei_now


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


def check_rate_limit(db: Session, user_id: int, stage: int) -> None:
    """
    Raises HTTP 429 if:
    - user exceeded STAGE_HOURLY_LIMIT calls for this stage in the past hour, or
    - user exceeded DAILY_API_LIMIT total external API calls today.
    """
    now = taipei_now()

    # Hourly per-stage limit
    one_hour_ago = now - timedelta(hours=1)
    hourly_count = (
        db.query(ApiUsageLog)
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

    # Daily total limit (stages 1, 3, 5, 6 and 7 consume AI APIs)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    daily_count = (
        db.query(ApiUsageLog)
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


def log_api_call(db: Session, user_id: int, stage: int) -> None:
    """Record an API call in api_usage_logs."""
    log = ApiUsageLog(user_id=user_id, stage=stage, called_at=taipei_now())
    db.add(log)
    db.commit()
