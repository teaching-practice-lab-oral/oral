import asyncio
from datetime import datetime

import pytest

from app.config import settings
from app.services import mail, result_delivery, storage


def test_result_token_is_deterministic_and_only_hash_is_persistable(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "a" * 64)
    first = result_delivery.result_download_token("package-id")
    second = result_delivery.result_download_token("package-id")
    assert first == second
    assert len(first) == 43
    assert result_delivery.result_download_token_hash(first) != first
    assert result_delivery.result_download_token("another-package") != first


def test_storage_namespace_isolated(monkeypatch):
    monkeypatch.setattr(settings, "OBJECT_STORAGE_NAMESPACE", "meet-20260725-a1")
    key = storage.object_key("audio", "S001", 9, "answer.mp3")
    assert key == "meet-20260725-a1/audio/S001/9/answer.mp3"
    assert storage.is_current_object_key(key, "audio")
    assert not storage.is_current_object_key("audio/S001/9/answer.mp3", "audio")
    with pytest.raises(ValueError, match="outside"):
        storage.download_file("audio/S001/9/answer.mp3")


def test_student_mailboxes_are_deduplicated():
    assert mail.student_recipients("Student@Example.com", "student@example.com") == [
        "Student@Example.com"
    ]
    assert mail.student_recipients("main@example.com", "backup@example.com") == [
        "main@example.com",
        "backup@example.com",
    ]
    assert mail.student_recipients("main@example.com", None) == ["main@example.com"]


def test_result_mail_sends_separate_messages_and_records_partial_failure(monkeypatch):
    sent_to = []

    async def fake_send(message, _conf):
        recipient = message.recipients[0]
        sent_to.append(list(message.recipients))
        if recipient == "backup@example.com":
            raise RuntimeError("SMTP unavailable")

    monkeypatch.setattr(mail, "_get_mail_config", lambda: object())
    monkeypatch.setattr(mail, "_send_message", fake_send)
    result = asyncio.run(
        mail.send_result_package_email(
            recipients=["main@example.com", "backup@example.com"],
            name="Student",
            assignment_title="Assignment",
            attempt_number=2,
            download_url="https://example.test/download",
            expires_at=datetime(2026, 8, 8, 12, 0),
        )
    )

    assert sent_to == [["main@example.com"], ["backup@example.com"]]
    assert result == {
        "main@example.com": True,
        "backup@example.com": False,
    }


def test_result_mail_reports_all_addresses_failed_without_losing_results(monkeypatch):
    async def fail_send(_message, _conf):
        raise RuntimeError("SMTP unavailable")

    monkeypatch.setattr(mail, "_get_mail_config", lambda: object())
    monkeypatch.setattr(mail, "_send_message", fail_send)
    result = asyncio.run(
        mail.send_result_package_email(
            recipients=["main@example.com", "backup@example.com"],
            name="Student",
            assignment_title="Assignment",
            attempt_number=1,
            download_url="https://example.test/download",
            expires_at=datetime(2026, 8, 8, 12, 0),
        )
    )
    recipients = [
        {"address": address, "status": "pending", "attempts": 0}
        for address in result
    ]
    updated, state, error = result_delivery.apply_recipient_delivery(
        recipients,
        result,
    )

    assert result == {
        "main@example.com": False,
        "backup@example.com": False,
    }
    assert state == "failed"
    assert error == "所有信箱皆寄送失敗"
    assert all(item["status"] == "failed" for item in updated)


def test_partial_retry_updates_only_failed_mailbox():
    recipients = [
        {
            "kind": "primary",
            "address": "main@example.com",
            "status": "sent",
            "attempts": 1,
            "error": None,
        },
        {
            "kind": "backup",
            "address": "backup@example.com",
            "status": "failed",
            "attempts": 1,
            "error": "SMTP 寄送失敗",
        },
    ]
    updated, state, error = result_delivery.apply_recipient_delivery(
        recipients,
        {"backup@example.com": True},
    )
    assert state == "sent"
    assert error is None
    assert updated[0]["attempts"] == 1
    assert updated[1]["attempts"] == 2
    assert all(item["status"] == "sent" for item in updated)
