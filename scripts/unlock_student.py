#!/usr/bin/env python3
"""Interactively clear the per-account login lock for one student.

Run this inside the application container so the existing DATABASE_URL and
application models are used::

    python scripts/unlock_student.py --student-id S12345678
"""

import argparse
import os
import sys
from typing import Any, Callable, TextIO


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear the failed-login count and account lock for one student"
    )
    parser.add_argument(
        "--student-id",
        required=True,
        dest="student_id",
        help="Student login ID to unlock",
    )
    return parser.parse_args(argv)


def _query_user(db: Any, user_model: Any, student_id: str, *, lock: bool = False) -> Any:
    query = db.query(user_model).filter(user_model.student_id == student_id)
    if lock:
        query = query.with_for_update()
    return query.first()


def _validation_error(user: Any, student_id: str) -> str | None:
    if user is None:
        return f"找不到學號 {student_id} 的帳號。"
    if user.role != "student":
        return f"帳號 {student_id} 不是學生帳號，已拒絕操作。"
    if not user.is_active:
        return f"學生帳號 {student_id} 已停用；請先透過帳號管理流程處理。"
    return None


def _is_fully_unlocked(user: Any) -> bool:
    return (user.failed_login_count or 0) == 0 and user.locked_until is None


def _print_account(user: Any, output: TextIO) -> None:
    locked_until = user.locked_until if user.locked_until is not None else "未設定"
    print("學生帳號資訊：", file=output)
    print(f"  學號：{user.student_id}", file=output)
    print(f"  姓名：{user.name}", file=output)
    print(f"  啟用狀態：{'是' if user.is_active else '否'}", file=output)
    print(f"  登入失敗次數：{user.failed_login_count or 0}", file=output)
    print(f"  鎖定至：{locked_until}", file=output)


def unlock_student_account(
    student_id: str,
    *,
    session_factory: Callable[[], Any],
    user_model: Any,
    input_fn: Callable[[], str] = input,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
) -> int:
    """Unlock one active student after an explicit interactive confirmation."""
    student_id = student_id.strip()
    if not student_id:
        print("ERROR: 學號不得為空。", file=error)
        return 1

    preview_db = session_factory()
    try:
        user = _query_user(preview_db, user_model, student_id)
        validation_error = _validation_error(user, student_id)
        if validation_error:
            print(f"ERROR: {validation_error}", file=error)
            preview_db.rollback()
            return 1

        _print_account(user, output)
        if _is_fully_unlocked(user):
            print("帳號目前已解除鎖定，無需變更。", file=output)
            preview_db.rollback()
            return 0
        preview_db.rollback()
    except Exception as exc:
        preview_db.rollback()
        print(f"ERROR: 讀取學生帳號失敗：{exc}", file=error)
        return 1
    finally:
        preview_db.close()

    print("請輸入 yes 確認解除此學生帳號的鎖定：", end=" ", file=output, flush=True)
    try:
        confirmation = input_fn().strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消，未變更任何資料。", file=output)
        return 1

    if confirmation != "yes":
        print("已取消，未變更任何資料。", file=output)
        return 1

    action_db = session_factory()
    try:
        user = _query_user(action_db, user_model, student_id, lock=True)
        validation_error = _validation_error(user, student_id)
        if validation_error:
            print(f"ERROR: {validation_error}", file=error)
            action_db.rollback()
            return 1

        if _is_fully_unlocked(user):
            action_db.rollback()
            print("帳號已由其他操作解除鎖定，無需變更。", file=output)
            return 0

        user.failed_login_count = 0
        user.locked_until = None
        action_db.commit()
    except Exception as exc:
        action_db.rollback()
        print(f"ERROR: 解除學生帳號鎖定失敗：{exc}", file=error)
        return 1
    finally:
        action_db.close()

    print(f"已解除學生帳號 {student_id} 的登入鎖定。", file=output)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from app.database import SessionLocal
    from app.models import User

    return unlock_student_account(
        args.student_id,
        session_factory=SessionLocal,
        user_model=User,
    )


if __name__ == "__main__":
    raise SystemExit(main())
