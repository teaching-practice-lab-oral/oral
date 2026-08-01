from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AdminAuditLog, Assignment, Submission, User
from app.utils import get_client_ip


_AUDIT_STRING_LIMIT = 500


def _trim_string(value: str, limit: int = _AUDIT_STRING_LIMIT) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"



def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _trim_string(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return _trim_string(value)



def _request_ip(request: Request | None) -> str | None:
    return get_client_ip(request)



def summarize_imported_users(users: list[Any], limit: int = 50) -> dict[str, Any]:
    items = []
    for user in users[:limit]:
        items.append(
            {
                "user_id": getattr(user, "user_id", None),
                "student_id": getattr(user, "student_id", None),
                "name": getattr(user, "name", None),
                "email": getattr(user, "email", None),
                "backup_email": getattr(user, "backup_email", None),
                "course_num": getattr(user, "course_num", None),
            }
        )
    return {
        "count": len(users),
        "items": items,
        "truncated": len(users) > limit,
    }



def snapshot_user(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "student_id": user.student_id,
        "name": user.name,
        "email": user.email,
        "backup_email": user.backup_email,
        "role": user.role,
        "course_num": user.course_num,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
    }



def snapshot_assignment(assignment: Assignment | None) -> dict[str, Any] | None:
    if assignment is None:
        return None
    return {
        "id": assignment.id,
        "title": assignment.title,
        "description": assignment.description,
        "course_nums": assignment.course_nums,
        "start_date": assignment.start_date,
        "due_date": assignment.due_date,
        "is_active": assignment.is_active,
        "rubric_version_id": assignment.rubric_version_id,
        "prompt_context": assignment.prompt_context,
        "questions": assignment.questions,
        "question_set_key": assignment.question_set_key,
    }



def snapshot_submission(submission: Submission | None) -> dict[str, Any] | None:
    if submission is None:
        return None
    return {
        "id": submission.id,
        "user_id": submission.user_id,
        "assignment_id": submission.assignment_id,
        "attempt_number": submission.attempt_number,
        "stage": submission.stage,
        "late_deadline": submission.late_deadline,
        "submitted_at": submission.submitted_at,
        "updated_at": submission.updated_at,
        "has_report": bool(getattr(submission, "report_data", None)),
    }




def log_admin_action(
    db: Session,
    admin: User,
    action: str,
    *,
    request: Request | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    target_label: str | None = None,
    summary: str | None = None,
    before: Any = None,
    after: Any = None,
    details: Any = None,
    result: str = "success",
) -> AdminAuditLog:
    entry = AdminAuditLog(
        admin_user_id=admin.id,
        admin_student_id=admin.student_id,
        admin_name=admin.name,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        target_label=target_label,
        result=result,
        summary=_trim_string(summary) if summary else None,
        before_json=_json_safe(before),
        after_json=_json_safe(after),
        detail_json=_json_safe(details),
        ip_address=_request_ip(request),
        user_agent=request.headers.get("User-Agent") if request else None,
    )
    db.add(entry)
    return entry


def log_actor_action(
    db: Session,
    action: str,
    *,
    actor_student_id: str,
    actor_name: str | None = None,
    actor_user: User | None = None,
    request: Request | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    target_label: str | None = None,
    summary: str | None = None,
    details: Any = None,
    result: str = "success",
) -> AdminAuditLog:
    """Record a sensitive action performed outside an authenticated admin session."""
    entry = AdminAuditLog(
        admin_user_id=actor_user.id if actor_user else None,
        admin_student_id=_trim_string(actor_student_id or "未識別", limit=64),
        admin_name=_trim_string(actor_name, limit=128) if actor_name else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        target_label=_trim_string(target_label) if target_label else None,
        result=result,
        summary=_trim_string(summary) if summary else None,
        detail_json=_json_safe(details),
        ip_address=_request_ip(request),
        user_agent=request.headers.get("User-Agent") if request else None,
    )
    db.add(entry)
    return entry
