"""Tamper-evident proof for short-lived imported-account plaintext credentials."""

import hashlib
import hmac

from app.config import settings


def _credential_message(user_id: int, password: str) -> bytes:
    return f"import-credential-v1\0{user_id}\0{password}".encode("utf-8")


def issue_import_credential_proof(user_id: int, password: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        _credential_message(user_id, password),
        hashlib.sha256,
    ).hexdigest()


def verify_import_credential_proof(user_id: int, password: str, proof: str) -> bool:
    expected = issue_import_credential_proof(user_id, password)
    return bool(proof) and hmac.compare_digest(expected, proof)
