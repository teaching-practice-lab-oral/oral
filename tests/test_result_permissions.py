from pathlib import Path

import pytest
from fastapi import HTTPException

from app.config import settings
from app.models import Assignment, User
from app.routers.admin.assignments import seed_preset_assignments
from app.services.admin_scope import (
    assignment_visible_to_admin,
    student_matches_assignment,
    student_visible_to_admin,
)


ROOT = Path(__file__).resolve().parents[1]


def test_non_protected_assignment_page_hides_privileged_controls_safely():
    controller = (ROOT / "app/static/admin/controllers/assignments.mjs").read_text()
    page = (ROOT / "app/static/admin/assignments.html").read_text()

    assert "btnPromptManagement" not in controller
    assert "['btnSeedPresets', 'btnSendReminders']" in controller
    assert 'class="btn btn-outline-secondary d-none" id="btnSeedPresets"' in page


def test_non_protected_admin_cannot_seed_preset_assignments(monkeypatch):
    monkeypatch.setattr(settings, "PROTECTED_ADMIN_STUDENT_ID", "MASTER")
    admin = User(id=1, student_id="COURSE-ADMIN", role="admin", course_num="A")

    with pytest.raises(HTTPException) as exc_info:
        seed_preset_assignments(request=None, admin=admin, db=None)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "只有指定管理員可同步預設作業"


def test_course_admin_cannot_deliver_outside_visible_scope(monkeypatch):
    monkeypatch.setattr(settings, "PROTECTED_ADMIN_STUDENT_ID", "MASTER")
    admin = User(id=1, student_id="TEACHER-A", role="admin", course_num="A")
    assignment = Assignment(title="A 班作業", course_nums=["A"])
    in_scope = User(id=2, student_id="A01", role="student", course_num="A")
    global_student = User(id=3, student_id="G01", role="student", course_num=None)
    out_of_scope = User(id=4, student_id="B01", role="student", course_num="B")

    assert assignment_visible_to_admin(admin, assignment)
    assert student_visible_to_admin(admin, in_scope)
    assert student_visible_to_admin(admin, global_student)
    assert student_matches_assignment(in_scope, assignment)
    assert not student_matches_assignment(global_student, assignment)
    assert not student_visible_to_admin(admin, out_of_scope)
    assert not student_matches_assignment(out_of_scope, assignment)
