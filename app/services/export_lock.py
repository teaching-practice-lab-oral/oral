"""Cluster-wide admission locks for bounded student result-package builds."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.config import settings
from app.database import engine as app_engine


_SUBMISSION_OPERATION = 1401
_GLOBAL_NAMESPACE = 1402

if app_engine.dialect.name == "postgresql":
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.STUDENT_EXPORT_MAX_CONCURRENCY,
        max_overflow=0,
        pool_timeout=settings.OPERATION_LOCK_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
    )
else:
    engine = app_engine

_local_guard = threading.Lock()
_local_submissions: set[int] = set()
_local_slots: set[int] = set()


def _busy_submission() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "student_export_in_progress", "message": "這份成果包正在建立中，請勿重複送出。"},
    )


def _busy_global() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": "student_export_capacity_reached", "message": "目前匯出工作較多，請稍後再試。"},
        headers={"Retry-After": "30"},
    )


@dataclass
class StudentExportLease:
    submission_id: int
    slot: int
    connection: Connection | None = None
    local: bool = False
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        if self.connection is not None:
            connection = self.connection
            self.connection = None
            try:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:namespace, :slot)"),
                    {"namespace": _GLOBAL_NAMESPACE, "slot": self.slot},
                )
                connection.execute(
                    text("SELECT pg_advisory_unlock(:submission_id, :operation)"),
                    {"submission_id": self.submission_id, "operation": _SUBMISSION_OPERATION},
                )
                connection.commit()
            except Exception:
                connection.invalidate()
                raise
            finally:
                connection.close()
        elif self.local:
            with _local_guard:
                _local_submissions.discard(self.submission_id)
                _local_slots.discard(self.slot)


def acquire_student_export_lease(submission_id: int) -> StudentExportLease:
    submission_id = int(submission_id)
    if not -(2**31) <= submission_id < 2**31:
        raise ValueError("submission_id must fit PostgreSQL advisory-lock int4")

    if engine.dialect.name == "postgresql":
        try:
            connection = engine.connect()
        except SQLAlchemyTimeoutError as exc:
            raise _busy_global() from exc
        try:
            submission_acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:submission_id, :operation)"),
                {"submission_id": submission_id, "operation": _SUBMISSION_OPERATION},
            ).scalar()
            if not submission_acquired:
                connection.close()
                raise _busy_submission()
            for slot in range(settings.STUDENT_EXPORT_MAX_CONCURRENCY):
                if connection.execute(
                    text("SELECT pg_try_advisory_lock(:namespace, :slot)"),
                    {"namespace": _GLOBAL_NAMESPACE, "slot": slot},
                ).scalar():
                    connection.commit()
                    return StudentExportLease(submission_id, slot, connection=connection)
            connection.execute(
                text("SELECT pg_advisory_unlock(:submission_id, :operation)"),
                {"submission_id": submission_id, "operation": _SUBMISSION_OPERATION},
            )
            connection.commit()
            connection.close()
            raise _busy_global()
        except HTTPException:
            raise
        except Exception:
            connection.invalidate()
            connection.close()
            raise

    with _local_guard:
        if submission_id in _local_submissions:
            raise _busy_submission()
        slot = next(
            (candidate for candidate in range(settings.STUDENT_EXPORT_MAX_CONCURRENCY) if candidate not in _local_slots),
            None,
        )
        if slot is None:
            raise _busy_global()
        _local_submissions.add(submission_id)
        _local_slots.add(slot)
    return StudentExportLease(submission_id, slot, local=True)
