from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from starlette.requests import Request
from fastapi import HTTPException

from app.legal_documents import PRIVACY_NOTICE_VERSION, SYSTEM_TERMS_VERSION
from app.models import User
from app.routers.auth import (
    _record_current_legal_acknowledgement,
    acknowledge_legal_documents,
)
from app.schemas import LegalAcknowledgementRequest


def _user(*, role: str = "student") -> User:
    return User(
        student_id="S0001",
        name="Test Student",
        email="student@example.edu.tw",
        hashed_password="unused",
        role=role,
    )


def test_student_must_acknowledge_both_current_versions():
    user = _user()
    assert user.requires_legal_acknowledgement is True

    old_time = datetime(2026, 7, 21, 12, 0)
    user.privacy_notice_version = "2026-07-21.2"
    user.privacy_acknowledged_at = old_time
    user.system_terms_version = "2026-07-21.2"
    user.system_terms_accepted_at = old_time
    assert user.requires_legal_acknowledgement is True

    user.privacy_notice_version = PRIVACY_NOTICE_VERSION
    user.system_terms_version = SYSTEM_TERMS_VERSION
    assert user.requires_legal_acknowledgement is False


def test_admin_does_not_enter_student_legal_gate():
    assert _user(role="admin").requires_legal_acknowledgement is False


def test_recording_acknowledgement_binds_versions_times_and_audit_event():
    user = _user()
    user.id = 42
    db = Mock()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/legal-acknowledgement",
            "headers": [(b"user-agent", b"pytest")],
            "client": ("127.0.0.1", 12345),
        }
    )

    _record_current_legal_acknowledgement(db, request, user)

    assert user.privacy_notice_version == PRIVACY_NOTICE_VERSION
    assert user.system_terms_version == SYSTEM_TERMS_VERSION
    assert user.privacy_acknowledged_at == user.system_terms_accepted_at
    assert user.legal_acknowledged_at == user.privacy_acknowledged_at
    db.add.assert_called_once()


def test_dedicated_acknowledgement_endpoint_does_not_require_password_change():
    user = _user()
    user.id = 42
    db = Mock()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/legal-acknowledgement",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )

    response = acknowledge_legal_documents(
        LegalAcknowledgementRequest(privacy_acknowledged=True, terms_accepted=True),
        request,
        user,
        db,
    )

    assert response.message == "法遵事項確認完成"
    assert user.requires_legal_acknowledgement is False
    db.commit.assert_called_once()


def test_dedicated_acknowledgement_rejects_missing_terms_acceptance():
    user = _user()
    user.id = 42
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/legal-acknowledgement",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )

    try:
        acknowledge_legal_documents(
            LegalAcknowledgementRequest(privacy_acknowledged=True, terms_accepted=False),
            request,
            user,
            Mock(),
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "使用者條款" in exc.detail
    else:
        raise AssertionError("missing terms acceptance must be rejected")


def test_student_ui_uses_dedicated_acknowledgement_endpoint_and_current_version():
    controller = Path("app/static/student/controllers/index-page.mjs").read_text(encoding="utf-8")
    page = Path("app/static/student/index.html").read_text(encoding="utf-8")

    assert "/api/auth/legal-acknowledgement" in controller
    assert "changePwAcknowledgementOnly" in controller
    assert PRIVACY_NOTICE_VERSION in page
    assert "index-page.mjs?v=7" in page
