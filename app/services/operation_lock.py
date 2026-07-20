"""Cross-worker single-flight locks for costly submission operations.

PostgreSQL advisory locks are bound to a dedicated connection, so the lock
remains held while the request releases its ordinary ORM session across slow
network calls.  SQLite and other test databases use a process-local fallback.
"""
import asyncio
import threading
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.engine import Connection

from app.config import settings
from app.database import engine as app_engine


# Keep advisory-lock sessions out of the ordinary ORM pool.  The small bounded
# pool intentionally turns excess concurrent costly operations into a quick
# 409 instead of allowing every request to hold two application connections.
if app_engine.dialect.name == "postgresql":
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.OPERATION_LOCK_POOL_SIZE,
        max_overflow=0,
        pool_timeout=settings.OPERATION_LOCK_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
    )
else:
    engine = app_engine


# Operations that can move stages 3-5 or spend on their derived media share
# one lease.  Aliasing these keys prevents both cross-route races and nested
# advisory-lock connections that could exhaust the SQLAlchemy pool.
PRACTICE_PREPARATION_OPERATION = 1001
SCAFFOLD_OPERATION = PRACTICE_PREPARATION_OPERATION
FEEDBACK_OPERATION = PRACTICE_PREPARATION_OPERATION
SHADOWING_OPERATION = PRACTICE_PREPARATION_OPERATION
SHADOWING_TTS_OPERATION = PRACTICE_PREPARATION_OPERATION
ROLEPLAY_START_OPERATION = 1201
ROLEPLAY_TURN_OPERATION = 1202
# A final turn and every report-regeneration entry point must be mutually
# exclusive.  The final-turn request already holds this lease through report
# generation, so it never needs a second dedicated DB connection.
ROLEPLAY_REPORT_OPERATION = ROLEPLAY_TURN_OPERATION

_BUSY_DETAIL = "這項操作正在處理中，請勿重複送出，稍後重新整理即可。"
_local_guard = threading.Lock()
_local_locks: set[tuple[int, int]] = set()


@dataclass
class OperationLockLease:
    submission_id: int
    operation_key: int
    connection: Connection | None = None
    local_key: tuple[int, int] | None = None
    _released: bool = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self.connection is not None:
            connection = self.connection
            self.connection = None

            def _unlock_and_close() -> None:
                try:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:submission_id, :operation_key)"),
                        {
                            "submission_id": self.submission_id,
                            "operation_key": self.operation_key,
                        },
                    )
                    connection.commit()
                except Exception:
                    # Never return a physical pooled connection that may still
                    # own a session-level advisory lock.
                    connection.invalidate()
                    raise
                finally:
                    connection.close()

            await asyncio.to_thread(_unlock_and_close)
        elif self.local_key is not None:
            with _local_guard:
                _local_locks.discard(self.local_key)


async def acquire_operation_lock(
    submission_id: int,
    operation_key: int,
) -> OperationLockLease:
    """Acquire a non-blocking submission operation lock or raise HTTP 409."""
    if not -(2**31) <= int(submission_id) < 2**31:
        raise ValueError("submission_id must fit PostgreSQL advisory-lock int4")
    if not -(2**31) <= int(operation_key) < 2**31:
        raise ValueError("operation_key must fit PostgreSQL advisory-lock int4")

    if engine.dialect.name == "postgresql":
        def _try_postgresql_lock() -> Connection | None:
            try:
                connection = engine.connect()
            except SQLAlchemyTimeoutError:
                return None
            try:
                acquired = connection.execute(
                    text("SELECT pg_try_advisory_lock(:submission_id, :operation_key)"),
                    {
                        "submission_id": int(submission_id),
                        "operation_key": int(operation_key),
                    },
                ).scalar()
                # Session-level advisory locks survive commit. Ending this
                # short transaction avoids an idle-in-transaction connection
                # during the slow external operation.
                connection.commit()
                if acquired:
                    return connection
            except Exception:
                # A failure after pg_try_advisory_lock may have acquired the
                # session lock. Invalidate instead of returning that physical
                # connection (and its lock) to the pool.
                connection.invalidate()
                connection.close()
                raise
            connection.close()
            return None

        connection = await asyncio.to_thread(_try_postgresql_lock)
        if connection is None:
            raise HTTPException(status_code=409, detail=_BUSY_DETAIL)
        return OperationLockLease(
            submission_id=int(submission_id),
            operation_key=int(operation_key),
            connection=connection,
        )

    local_key = (int(submission_id), int(operation_key))
    with _local_guard:
        if local_key in _local_locks:
            raise HTTPException(status_code=409, detail=_BUSY_DETAIL)
        _local_locks.add(local_key)
    return OperationLockLease(
        submission_id=int(submission_id),
        operation_key=int(operation_key),
        local_key=local_key,
    )
