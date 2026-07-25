from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import settings
from app.routers import result_downloads
from app.services.result_delivery import (
    result_download_token,
    result_download_token_hash,
)
from app.utils import taipei_now


class _PackageQuery:
    def __init__(self, package):
        self.package = package

    def filter(self, *_args):
        return self

    def first(self):
        return self.package


class _PackageDb:
    def __init__(self, package):
        self.package = package
        self.commits = 0

    def query(self, _model):
        return _PackageQuery(self.package)

    def commit(self):
        self.commits += 1


def _package(token: str, **overrides):
    values = {
        "token_hash": result_download_token_hash(token),
        "object_key": "generation/result-packages/package/result.zip",
        "expires_at": taipei_now() + timedelta(days=1),
        "state": "sent",
        "filename": "成果.zip",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_valid_result_token_can_be_reused_and_redirect_is_short_lived(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "a" * 64)
    monkeypatch.setattr(settings, "OBJECT_STORAGE_NAMESPACE", "generation")
    monkeypatch.setattr(settings, "RESULT_DOWNLOAD_REDIRECT_SECONDS", 300)
    token = result_download_token("package-id")
    db = _PackageDb(_package(token))
    calls = []
    monkeypatch.setattr(result_downloads.storage, "object_exists", lambda _key: True)

    def presign(key, expiration, *, download_filename):
        calls.append((key, expiration, download_filename))
        return "https://objects.example.test/temporary"

    monkeypatch.setattr(result_downloads.storage, "generate_presigned_url", presign)

    first = result_downloads.download_result_package(token, db)
    second = result_downloads.download_result_package(token, db)

    assert first.status_code == second.status_code == 302
    assert first.headers["location"] == "https://objects.example.test/temporary"
    assert calls == [
        ("generation/result-packages/package/result.zip", 300, "成果.zip"),
        ("generation/result-packages/package/result.zip", 300, "成果.zip"),
    ]


@pytest.mark.parametrize(
    ("token", "package", "status_code"),
    [
        ("not-a-token", None, 404),
        ("x" * 43, None, 404),
    ],
)
def test_forged_result_token_is_not_disclosed(token, package, status_code):
    with pytest.raises(HTTPException) as exc_info:
        result_downloads.download_result_package(token, _PackageDb(package))
    assert exc_info.value.status_code == status_code


def test_expired_or_deleted_result_package_returns_gone(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "b" * 64)
    monkeypatch.setattr(settings, "OBJECT_STORAGE_NAMESPACE", "generation")
    token = result_download_token("package-id")
    expired = _package(token, expires_at=taipei_now() - timedelta(seconds=1))
    with pytest.raises(HTTPException) as expired_error:
        result_downloads.download_result_package(token, _PackageDb(expired))
    assert expired_error.value.status_code == 410

    deleted = _package(token)
    db = _PackageDb(deleted)
    monkeypatch.setattr(result_downloads.storage, "object_exists", lambda _key: False)
    with pytest.raises(HTTPException) as deleted_error:
        result_downloads.download_result_package(token, db)
    assert deleted_error.value.status_code == 410
    assert deleted.state == "expired"
    assert db.commits == 1
