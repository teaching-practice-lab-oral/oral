from __future__ import annotations

from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import and_, or_

from app.config import settings
from app.models import Assignment, User


def normalize_course_num(course_num: Optional[str]) -> Optional[str]:
    if course_num is None:
        return None
    value = str(course_num).strip()
    return value or None


def normalize_course_nums(course_nums: Optional[Iterable[str]]) -> Optional[list[str]]:
    if not course_nums:
        return None

    normalized: list[str] = []
    seen: set[str] = set()
    for course_num in course_nums:
        value = normalize_course_num(course_num)
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized or None


def is_privileged_admin(admin: User) -> bool:
    return bool(settings.PROTECTED_ADMIN_STUDENT_ID) and admin.student_id == settings.PROTECTED_ADMIN_STUDENT_ID


def ensure_privileged_admin(admin: User, detail: str = "只有指定管理員可執行此操作") -> None:
    if not is_privileged_admin(admin):
        raise HTTPException(status_code=403, detail=detail)


def get_admin_course_num(admin: User) -> Optional[str]:
    return normalize_course_num(admin.course_num)


def course_num_visible_to_admin(admin: User, course_num: Optional[str]) -> bool:
    if is_privileged_admin(admin):
        return True
    value = normalize_course_num(course_num)
    admin_course_num = get_admin_course_num(admin)
    return value is None or value == admin_course_num


def assignment_visible_to_admin(admin: User, assignment: Assignment) -> bool:
    if is_privileged_admin(admin):
        return True
    course_nums = normalize_course_nums(assignment.course_nums)
    if not course_nums:
        return True
    admin_course_num = get_admin_course_num(admin)
    return bool(admin_course_num) and admin_course_num in course_nums


def student_visible_to_admin(admin: User, student: User) -> bool:
    if student.role != "student":
        return is_privileged_admin(admin) or student.id == admin.id
    return course_num_visible_to_admin(admin, student.course_num)


def student_matches_assignment(student: User, assignment: Assignment) -> bool:
    course_nums = normalize_course_nums(assignment.course_nums)
    if not course_nums:
        return True
    return normalize_course_num(student.course_num) in course_nums


def ensure_admin_can_access_assignment(admin: User, assignment: Assignment) -> None:
    if not assignment_visible_to_admin(admin, assignment):
        raise HTTPException(status_code=403, detail="您無權存取這個作業")


def ensure_admin_can_mutate_assignment(admin: User, assignment: Assignment) -> None:
    """Limit assignment-wide mutations to one administrator-owned course.

    Global and multi-course assignments remain readable so course
    administrators can review and grade their own students.  Their shared
    configuration affects students outside one course, however, so only the
    privileged administrator may change assignment-wide state.
    """
    ensure_admin_can_access_assignment(admin, assignment)
    if is_privileged_admin(admin):
        return
    course_nums = normalize_course_nums(assignment.course_nums)
    admin_course_num = get_admin_course_num(admin)
    if not admin_course_num or course_nums != [admin_course_num]:
        raise HTTPException(status_code=403, detail="只有最高權限管理員可以修改全域或跨課程作業")


def ensure_admin_can_reset_visible_submissions(admin: User, assignment: Assignment) -> None:
    """Authorize a course-local reset without granting assignment-wide control."""
    ensure_admin_can_access_assignment(admin, assignment)
    if not is_privileged_admin(admin) and normalize_course_nums(assignment.course_nums) is None:
        raise HTTPException(status_code=403, detail="只有最高權限管理員可以重設全域作業")


def ensure_admin_can_access_user(admin: User, user: User) -> None:
    if not student_visible_to_admin(admin, user):
        raise HTTPException(status_code=403, detail="您無權存取這位學生")


def ensure_admin_can_access_student_assignment(admin: User, student: User, assignment: Assignment) -> None:
    ensure_admin_can_access_assignment(admin, assignment)
    ensure_admin_can_access_user(admin, student)
    if student.role != "student":
        raise HTTPException(status_code=400, detail="目標使用者不是學生")
    if not student_matches_assignment(student, assignment):
        raise HTTPException(status_code=403, detail="這位學生不在此作業的可見範圍內")


def ensure_admin_can_assign_course_num(admin: User, course_num: Optional[str]) -> None:
    if not course_num_visible_to_admin(admin, course_num):
        raise HTTPException(status_code=403, detail="只能指定未設課號或與自己相同的課號")


def ensure_admin_can_assign_course_nums(admin: User, course_nums: Optional[Iterable[str]]) -> list[str] | None:
    normalized = normalize_course_nums(course_nums)
    if is_privileged_admin(admin):
        return normalized
    if normalized is None:
        raise HTTPException(status_code=403, detail="非最高權限管理員建立或編輯作業時必須指定自己的課號")
    admin_course_num = get_admin_course_num(admin)
    disallowed = [course_num for course_num in normalized or [] if course_num != admin_course_num]
    if disallowed:
        raise HTTPException(status_code=403, detail="只能指定未設課號或與自己相同的課號")
    return normalized


def apply_student_visibility_filter(query, admin: User):
    if is_privileged_admin(admin):
        return query.filter(User.role == "student")
    admin_course_num = get_admin_course_num(admin)
    if admin_course_num:
        return query.filter(
            User.role == "student",
            or_(User.course_num.is_(None), User.course_num == admin_course_num),
        )
    return query.filter(User.role == "student", User.course_num.is_(None))


def apply_user_visibility_filter(query, admin: User, *, include_admins: bool = True):
    if is_privileged_admin(admin):
        return query
    admin_course_num = get_admin_course_num(admin)
    if admin_course_num:
        student_clause = and_(
            User.role == "student",
            or_(User.course_num.is_(None), User.course_num == admin_course_num),
        )
    else:
        student_clause = and_(User.role == "student", User.course_num.is_(None))
    if include_admins:
        # Course administrators may audit their own sign-ins/sessions, but IP
        # and device metadata for other administrators is privileged data.
        return query.filter(or_(User.id == admin.id, student_clause))
    return query.filter(student_clause)
