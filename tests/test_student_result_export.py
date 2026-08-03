import asyncio
import json
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


def test_student_result_export_is_owned_graded_and_uses_shared_builder(monkeypatch):
    student = User(id=2, student_id="S002", name="學生")
    assignment = Assignment(id=10, title="個人背景與動機")
    submission = _submission()
    grade = SimpleNamespace(origin_submission_id=submission.id)
    calls = {}

    def owned_submission(db, submission_id, user_id):
        calls["ownership"] = (submission_id, user_id)
        return submission

    def build_package(output, db, received_student, received_assignment, received_submission, received_grade):
        calls["output"] = output
        calls["builder"] = (
            received_student,
            received_assignment,
            received_submission,
            received_grade,
        )
        payload = b"x" * (128 * 1024)
        output.write(payload)
        output.seek(0)
        return len(payload)

    class Lease:
        def release(self):
            calls["lease_released"] = True

    monkeypatch.setattr(student_exports, "get_own_submission", owned_submission)
    monkeypatch.setattr(student_exports, "latest_grade", lambda _db, _id: grade)
    monkeypatch.setattr(
        student_exports,
        "write_graded_submission_result_package",
        build_package,
    )
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
    assert response.media_type == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert "%E5%AD%B8%E7%BF%92%E6%88%90%E6%9E%9C.zip" in response.headers[
        "content-disposition"
    ]

    async def disconnect_immediately():
        body_send_started = asyncio.Event()

        async def receive():
            await body_send_started.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("more_body"):
                body_send_started.set()
                await asyncio.sleep(1)

        await response(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "method": "GET",
                "path": "/download",
                "headers": [],
            },
            receive,
            send,
        )

    assert calls["output"].closed is False
    asyncio.run(disconnect_immediately())
    assert calls["output"].closed is True


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


def test_student_index_busts_export_controller_cache():
    html = (ROOT / "app/static/student/index.html").read_text(encoding="utf-8")
    assert "/static/student/controllers/index-page.mjs?v=11" in html
