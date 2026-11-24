import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import Assignment, User
from app.routers.student import exports as student_exports
from app.services import result_delivery


ROOT = Path(__file__).resolve().parents[1]


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


def _patch_latest(monkeypatch, latest):
    monkeypatch.setattr(
        student_exports,
        "get_latest_submission",
        lambda _db, _user_id, _assignment_id, submitted_only=False: latest,
    )


def test_student_result_export_is_owned_graded_and_returns_word_only(monkeypatch):
    student = User(id=2, student_id="S002", name="學生")
    assignment = Assignment(id=10, title="個人背景與動機")
    submission = _submission()
    grade = SimpleNamespace(origin_submission_id=submission.id)
    calls = {}

    def owned_submission(db, submission_id, user_id):
        calls["ownership"] = (submission_id, user_id)
        return submission

    def build_report(db, received_student, received_assignment, received_submission, received_grade):
        calls["builder"] = (
            received_student,
            received_assignment,
            received_submission,
            received_grade,
        )
        return b"docx-bytes"

    class Lease:
        def release(self):
            calls["lease_released"] = True

    monkeypatch.setattr(student_exports, "get_own_submission", owned_submission)
    _patch_latest(monkeypatch, submission)
    monkeypatch.setattr(student_exports, "latest_grade", lambda _db, _id: grade)
    monkeypatch.setattr(student_exports, "build_graded_submission_report", build_report)
    monkeypatch.setattr(student_exports.rate_limiter, "reserve_costly_action", lambda *args, **kwargs: calls.setdefault("rate", (args, kwargs)))
    monkeypatch.setattr(student_exports, "acquire_student_export_lease", lambda _id: Lease())

    response = student_exports.export_result_package(
        submission.id,
        current_user=student,
        db=_ExportDb(assignment),
    )

    assert calls["ownership"] == (submission.id, student.id)
    assert calls["builder"] == (student, assignment, submission, grade)
    assert calls["lease_released"] is True
    assert response.body == b"docx-bytes"
    assert response.media_type == student_exports.DOCX_MEDIA_TYPE
    assert response.headers["cache-control"] == "no-store"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith(".docx")


def test_student_result_export_rejects_older_attempt(monkeypatch):
    student = User(id=2, student_id="S002", name="學生")
    assignment = Assignment(id=10, title="個人背景與動機")
    submission = _submission()
    newer = SimpleNamespace(id=submission.id + 1)
    monkeypatch.setattr(
        student_exports,
        "get_own_submission",
        lambda _db, _submission_id, _user_id: submission,
    )
    _patch_latest(monkeypatch, newer)

    with pytest.raises(HTTPException) as exc_info:
        student_exports.export_result_package(
            submission.id,
            current_user=student,
            db=_ExportDb(assignment),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "只能匯出最新一次完成的作業"


def test_student_result_export_rejects_ungraded_submission(monkeypatch):
    student = User(id=2, student_id="S002", name="學生")
    assignment = Assignment(id=10, title="個人背景與動機")
    submission = _submission()
    monkeypatch.setattr(
        student_exports,
        "get_own_submission",
        lambda _db, _submission_id, _user_id: submission,
    )
    _patch_latest(monkeypatch, submission)
    monkeypatch.setattr(student_exports, "latest_grade", lambda _db, _id: None)

    with pytest.raises(HTTPException) as exc_info:
        student_exports.export_result_package(
            submission.id,
            current_user=student,
            db=_ExportDb(assignment),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "老師還沒批改完，暫時無法匯出"


def test_student_report_builder_binds_requested_grade_without_audio(monkeypatch):
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
        "build_submission_docx",
        lambda received_student, received_assignment, received_submission: (
            calls.append(("docx", received_student, received_assignment, received_submission))
            or b"docx"
        ),
    )

    payload = result_delivery.build_graded_submission_report(
        "db",
        student,
        assignment,
        submission,
        grade,
    )

    assert payload == b"docx"
    assert submission.latest_grade_data == {"grade_id": submission.id}
    assert calls == [
        ("hydrate", "db", submission),
        ("docx", student, assignment, submission),
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_api_error_message_handles_structured_fastapi_detail():
    module_uri = (ROOT / "app/static/student/api-error.mjs").as_uri()
    script = f"""
      import {{ apiErrorMessage }} from {json.dumps(module_uri)};
      const values = [
        apiErrorMessage({{detail: {{code: 'limited', message: '請稍後再試。'}}}}, 'fallback'),
        apiErrorMessage({{detail: '一般錯誤'}}, 'fallback'),
        apiErrorMessage(null, 'fallback'),
      ];
      process.stdout.write(JSON.stringify(values));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == ["請稍後再試。", "一般錯誤", "fallback"]

