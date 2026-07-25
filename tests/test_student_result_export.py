from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import Assignment, User
from app.routers.student import exports as student_exports
from app.services import result_delivery


class _ExportDb:
    def __init__(self, assignment):
        self.assignment = assignment

    def get(self, model, identity):
        assert model is Assignment
        assert identity == self.assignment.id
        return self.assignment


def _submission():
    return SimpleNamespace(
        id=7,
        user_id=2,
        assignment_id=10,
        attempt_number=3,
        submitted_at=datetime(2026, 7, 26, 12, 0),
    )


def test_student_result_export_is_owned_graded_and_uses_shared_builder(monkeypatch):
    student = User(id=2, student_id="S002", name="學生")
    assignment = Assignment(id=10, title="個人背景與動機")
    submission = _submission()
    grade = SimpleNamespace(origin_submission_id=submission.id)
    calls = {}

    def owned_submission(db, submission_id, user_id):
        calls["ownership"] = (submission_id, user_id)
        return submission

    def build_package(db, received_student, received_assignment, received_submission, received_grade):
        calls["builder"] = (
            received_student,
            received_assignment,
            received_submission,
            received_grade,
        )
        return b"complete-result-package"

    monkeypatch.setattr(student_exports, "get_own_submission", owned_submission)
    monkeypatch.setattr(student_exports, "latest_grade", lambda _db, _id: grade)
    monkeypatch.setattr(
        student_exports,
        "build_graded_submission_result_package",
        build_package,
    )

    response = student_exports.export_result_package(
        submission.id,
        current_user=student,
        db=_ExportDb(assignment),
    )

    assert calls["ownership"] == (submission.id, student.id)
    assert calls["builder"] == (student, assignment, submission, grade)
    assert response.media_type == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert "%E5%AD%B8%E7%BF%92%E6%88%90%E6%9E%9C.zip" in response.headers[
        "content-disposition"
    ]


def test_student_result_export_rejects_ungraded_submission(monkeypatch):
    student = User(id=2, student_id="S002", name="學生")
    assignment = Assignment(id=10, title="個人背景與動機")
    submission = _submission()
    monkeypatch.setattr(
        student_exports,
        "get_own_submission",
        lambda _db, _submission_id, _user_id: submission,
    )
    monkeypatch.setattr(student_exports, "latest_grade", lambda _db, _id: None)

    with pytest.raises(HTTPException) as exc_info:
        student_exports.export_result_package(
            submission.id,
            current_user=student,
            db=_ExportDb(assignment),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "老師尚未完成批改，暫時無法匯出成果包"


def test_shared_result_package_builder_binds_requested_grade(monkeypatch):
    student = SimpleNamespace(id=2)
    assignment = SimpleNamespace(id=10)
    submission = _submission()
    grade = SimpleNamespace(origin_submission_id=submission.id)
    calls = []

    monkeypatch.setattr(
        result_delivery,
        "hydrate_submission_from_normalized",
        lambda db, item: calls.append(("hydrate", db, item)),
    )
    monkeypatch.setattr(
        result_delivery,
        "grade_admin_payload",
        lambda item: {"grade_id": item.origin_submission_id},
    )
    monkeypatch.setattr(
        result_delivery,
        "build_submission_result_package",
        lambda received_student, received_assignment, received_submission: (
            calls.append(
                (
                    "build",
                    received_student,
                    received_assignment,
                    received_submission,
                )
            )
            or b"zip"
        ),
    )

    payload = result_delivery.build_graded_submission_result_package(
        "db",
        student,
        assignment,
        submission,
        grade,
    )

    assert payload == b"zip"
    assert submission.latest_grade_data == {"grade_id": submission.id}
    assert calls == [
        ("hydrate", "db", submission),
        ("build", student, assignment, submission),
    ]
