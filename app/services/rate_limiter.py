from datetime import timedelta
from enum import Enum, IntEnum
from typing import Callable

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ApiUsageLog, CostlyActionUsageLog, LoginEvent, User
from app.config import settings
from app.utils import taipei_now


class ExternalApiStage(IntEnum):
    JOB_PROFILE = 1
    WRITING_FEEDBACK = 3
    SHADOWING = 5
    ROLEPLAY = 6
    FINAL_REPORT = 7


class CostlyAction(str, Enum):
    AUDIO_UPLOAD = "audio_upload"
    PHOTO_UPLOAD = "photo_upload"
    STUDENT_RESULT_EXPORT = "student_result_export"


def _cost_limit_error(message: str, retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": "costly_action_rate_limited", "message": message},
        headers={"Retry-After": str(max(1, int(retry_after)))},
    )


def reserve_costly_action(
    user_id: int,
    action: CostlyAction,
    *,
    resource_id: str | int | None = None,
    units_bytes: int = 0,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """Atomically admit one attacker-controlled, CPU/network-heavy operation."""
    try:
        action = CostlyAction(action)
    except ValueError as exc:
        raise ValueError(f"Unsupported costly action: {action}") from exc
    units_bytes = int(units_bytes)
    if units_bytes < 0:
        raise ValueError("units_bytes must be nonnegative")
    normalized_resource = str(resource_id)[:64] if resource_id is not None else None
    if action is CostlyAction.STUDENT_RESULT_EXPORT and not normalized_resource:
        raise ValueError("student export rate admission requires resource_id")

    now = taipei_now()
    with (session_factory or SessionLocal)() as quota_db:
        try:
            user = (
                quota_db.query(User)
                .filter(User.id == user_id)
                .with_for_update()
                .first()
            )
            if user is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="使用者不存在或已失效。")

            base = quota_db.query(CostlyActionUsageLog).filter(
                CostlyActionUsageLog.user_id == user_id,
                CostlyActionUsageLog.action == action.value,
            )
            if action is CostlyAction.AUDIO_UPLOAD:
                window = timedelta(minutes=settings.AUDIO_UPLOAD_WINDOW_MINUTES)
                count = base.filter(CostlyActionUsageLog.called_at >= now - window).count()
                if count >= settings.AUDIO_UPLOAD_WINDOW_LIMIT:
                    raise _cost_limit_error("錄音上傳過於頻繁，請稍後再試。", int(window.total_seconds()))
            elif action is CostlyAction.PHOTO_UPLOAD:
                one_hour = timedelta(hours=1)
                count = base.filter(CostlyActionUsageLog.called_at >= now - one_hour).count()
                if count >= settings.PHOTO_UPLOAD_HOURLY_LIMIT:
                    raise _cost_limit_error("照片上傳過於頻繁，請稍後再試。", 3600)
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                used_bytes = quota_db.query(
                    func.coalesce(func.sum(CostlyActionUsageLog.units_bytes), 0)
                ).filter(
                    CostlyActionUsageLog.user_id == user_id,
                    CostlyActionUsageLog.action == action.value,
                    CostlyActionUsageLog.called_at >= today_start,
                ).scalar()
                if int(used_bytes or 0) + units_bytes > settings.PHOTO_UPLOAD_DAILY_BYTES:
                    raise _cost_limit_error("今日照片上傳總量已達上限，請明日再試。", 86400)
            else:
                one_hour = timedelta(hours=1)
                count = base.filter(CostlyActionUsageLog.called_at >= now - one_hour).count()
                if count >= settings.STUDENT_EXPORT_HOURLY_LIMIT:
                    raise _cost_limit_error("成果包匯出過於頻繁，請稍後再試。", 3600)
                resource_window = timedelta(minutes=settings.STUDENT_EXPORT_RESOURCE_WINDOW_MINUTES)
                resource_count = base.filter(
                    CostlyActionUsageLog.resource_id == normalized_resource,
                    CostlyActionUsageLog.called_at >= now - resource_window,
                ).count()
                if resource_count >= settings.STUDENT_EXPORT_RESOURCE_WINDOW_LIMIT:
                    raise _cost_limit_error("這份成果包匯出過於頻繁，請稍後再試。", int(resource_window.total_seconds()))

            quota_db.add(
                CostlyActionUsageLog(
                    user_id=user_id,
                    action=action.value,
                    resource_id=normalized_resource,
                    units_bytes=units_bytes,
                    called_at=now,
                )
            )
            quota_db.commit()
        except Exception:
            quota_db.rollback()
            raise


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
