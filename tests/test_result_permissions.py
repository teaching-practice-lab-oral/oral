from app.config import settings
from app.models import Assignment, User
from app.services.admin_scope import (
    assignment_visible_to_admin,
    student_matches_assignment,
    student_visible_to_admin,
)


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
