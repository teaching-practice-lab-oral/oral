"""Client for optional stateless audio/TTS offload to the CHT worker VM."""
import base64
import contextvars
import logging
import random
import time
from contextlib import contextmanager
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_cooldown_until = 0.0
_routing_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("worker_routing_context", default={})


@contextmanager
def routing_context(
    *,
    user_id: int | None = None,
    student_id: str | None = None,
    submission_id: int | None = None,
    stage: int | None = None,
    operation: str,
):
    token = _routing_context.set({
        "user_id": user_id,
        "student_id": student_id,
        "submission_id": submission_id,
        "stage": stage,
        "operation": operation,
    })
    try:
        yield
    finally:
        _routing_context.reset(token)


def _base_url() -> str:
    return settings.CHT_WORKER_BASE_URL.rstrip("/")


def _route_decision() -> tuple[bool, str]:
    if not settings.CHT_WORKER_ENABLED or not settings.CHT_WORKER_SECRET or not settings.CHT_WORKER_BASE_URL.strip():
        return False, "local_disabled"
    weight = settings.cht_worker_weight_ratio
    if weight <= 0:
        return False, "local_weight"
    if time.monotonic() < _cooldown_until:
        return False, "local_cooldown"
    if random.random() >= weight:
        return False, "local_weight"
    return True, "worker"


def should_use_worker() -> bool:
    """Return whether this request should be delegated to the worker."""
    use_worker, _status = _route_decision()
    return use_worker


def _mark_worker_failure() -> None:
    global _cooldown_until
    cooldown = max(0, settings.CHT_WORKER_COOLDOWN_SECONDS)
    if cooldown:
        _cooldown_until = time.monotonic() + cooldown


def _record_event(route_status: str, *, detail: str | None = None, duration_ms: int | None = None) -> None:
    ctx = _routing_context.get()
    student_id = ctx.get("student_id")
    operation = ctx.get("operation")
    if not student_id or not operation:
        return

    try:
        from app.database import SessionLocal
        from app.models import WorkerRoutingEvent

        db = SessionLocal()
        try:
            db.add(WorkerRoutingEvent(
                user_id=ctx.get("user_id"),
                student_id=str(student_id),
                submission_id=ctx.get("submission_id"),
                stage=ctx.get("stage"),
                operation=str(operation)[:64],
                route_status=route_status,
                worker_url=_base_url() if settings.CHT_WORKER_BASE_URL.strip() else None,
                detail=(detail or "")[:256] or None,
                duration_ms=duration_ms,
            ))
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Could not record CHT worker routing event: %s", exc)


async def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    use_worker, local_status = _route_decision()
    if not use_worker:
        _record_event(local_status)
        return None

    url = f"{_base_url()}{path}"
    headers = {"Authorization": f"Bearer {settings.CHT_WORKER_SECRET}"}
    timeout = httpx.Timeout(
        connect=10.0,
        read=settings.CHT_WORKER_TIMEOUT_SECONDS,
        write=settings.CHT_WORKER_TIMEOUT_SECONDS,
        pool=5.0,
    )
    try:
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("CHT worker request failed for %s: %s", path, exc)
        _mark_worker_failure()
        _record_event("fallback_error", detail=str(exc), duration_ms=int((time.monotonic() - started) * 1000))
        return None
    if not isinstance(data, dict):
        logger.warning("CHT worker returned non-object JSON for %s", path)
        _mark_worker_failure()
        _record_event("fallback_error", detail="Worker returned non-object JSON", duration_ms=int((time.monotonic() - started) * 1000))
        return None
    data["_worker_duration_ms"] = int((time.monotonic() - started) * 1000)
    return data


async def check_health() -> dict[str, Any]:
    """Probe the configured worker health endpoint for admin diagnostics."""
    if not settings.CHT_WORKER_ENABLED:
        return {
            "online": False,
            "configured": False,
            "base_url": settings.CHT_WORKER_BASE_URL,
            "detail": "CHT worker offload is disabled",
        }
    if not settings.CHT_WORKER_BASE_URL.strip() or not settings.CHT_WORKER_SECRET:
        return {
            "online": False,
            "configured": False,
            "base_url": settings.CHT_WORKER_BASE_URL,
            "detail": "CHT worker URL or secret is not configured",
        }

    url = f"{_base_url()}/internal/worker/health"
    headers = {"Authorization": f"Bearer {settings.CHT_WORKER_SECRET}"}
    timeout = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=2.0)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            duration_ms = int((time.monotonic() - started) * 1000)
            if response.status_code == 200:
                return {
                    "online": True,
                    "configured": True,
                    "base_url": _base_url(),
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "detail": "Worker health check passed",
                }
            return {
                "online": False,
                "configured": True,
                "base_url": _base_url(),
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "detail": f"Worker health returned HTTP {response.status_code}",
            }
    except Exception as exc:
        return {
            "online": False,
            "configured": True,
            "base_url": _base_url(),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "detail": str(exc),
        }


async def generate_speech(
    text: str,
    voice: str | None = None,
    speed: float | None = None,
) -> bytes | None:
    """Return MP3 bytes from the worker, or None when local fallback should run."""
    data = await _post_json("/internal/worker/tts", {
        "text": text,
        "voice": voice,
        "speed": speed,
    })
    if data is None:
        return None
    audio_b64 = data.get("audio_base64")
    if not isinstance(audio_b64, str):
        logger.warning("CHT worker TTS response missing audio_base64")
        _mark_worker_failure()
        _record_event("fallback_error", detail="Worker TTS response missing audio_base64")
        return None
    try:
        audio = base64.b64decode(audio_b64, validate=True)
        _record_event("worker_success", duration_ms=data.get("_worker_duration_ms"))
        return audio
    except Exception as exc:
        logger.warning("CHT worker TTS response has invalid audio_base64: %s", exc)
        _mark_worker_failure()
        _record_event("fallback_error", detail=f"Invalid TTS audio_base64: {exc}")
        return None


async def process_audio(
    audio_bytes: bytes,
    filename: str,
) -> tuple[bytes, str, dict | None] | None:
    """Return processed MP3/transcript/metrics, or None for local fallback."""
    data = await _post_json("/internal/worker/audio/process", {
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "filename": filename,
    })
    if data is None:
        return None
    audio_b64 = data.get("mp3_base64")
    transcript = data.get("transcript")
    metrics = data.get("metrics")
    if not isinstance(audio_b64, str) or not isinstance(transcript, str):
        logger.warning("CHT worker audio response missing mp3_base64/transcript")
        _mark_worker_failure()
        _record_event("fallback_error", detail="Worker audio response missing mp3_base64/transcript")
        return None
    if metrics is not None and not isinstance(metrics, dict):
        logger.warning("CHT worker audio response has invalid metrics")
        _mark_worker_failure()
        _record_event("fallback_error", detail="Worker audio response has invalid metrics")
        return None
    try:
        mp3_bytes = base64.b64decode(audio_b64, validate=True)
    except Exception as exc:
        logger.warning("CHT worker audio response has invalid mp3_base64: %s", exc)
        _mark_worker_failure()
        _record_event("fallback_error", detail=f"Invalid audio mp3_base64: {exc}")
        return None
    _record_event("worker_success", duration_ms=data.get("_worker_duration_ms"))
    return mp3_bytes, transcript, metrics
