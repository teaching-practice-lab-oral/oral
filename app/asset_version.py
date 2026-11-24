"""Automatic cache-busting for /static assets.

Every ``/static/...(.js|.mjs|.css|.html)`` URL in served HTML and JavaScript is
rewritten to ``?v=<hash of the static tree>``.  Source files therefore carry no
hand-maintained ``?v=N`` numbers: any change under ``app/static`` yields a new
version, so browsers fetch fresh modules after a deploy (or, in development,
after an edit to the mounted files) instead of serving a cached copy for up to
the static max-age.
"""
import hashlib
import os
import re
import threading
import time
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"

_ASSET_URL_RE = re.compile(rb"(/static/[A-Za-z0-9_./-]+\.(?:mjs|js|css|html))(?:\?v=[A-Za-z0-9_.-]*)?")
_RECHECK_SECONDS = 2.0
_lock = threading.Lock()
_state: dict = {"checked_at": float("-inf"), "fingerprint": None, "version": ""}


def _files(static_dir: Path):
    for root, dirs, names in os.walk(static_dir):
        dirs.sort()
        for name in sorted(names):
            yield Path(root) / name


def _fingerprint(static_dir: Path) -> tuple:
    entries = []
    for path in _files(static_dir):
        stat = path.stat()
        entries.append((str(path.relative_to(static_dir)), stat.st_size, stat.st_mtime_ns))
    return tuple(entries)


def compute_asset_version(static_dir: Path = STATIC_DIR) -> str:
    digest = hashlib.sha256()
    for path in _files(static_dir):
        digest.update(str(path.relative_to(static_dir)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def asset_version() -> str:
    """Return the current static-tree version, re-checking at most every 2s."""
    now = time.monotonic()
    if now - _state["checked_at"] < _RECHECK_SECONDS:
        return _state["version"]
    with _lock:
        if now - _state["checked_at"] >= _RECHECK_SECONDS:
            fingerprint = _fingerprint(STATIC_DIR)
            if fingerprint != _state["fingerprint"]:
                _state["version"] = compute_asset_version(STATIC_DIR)
                _state["fingerprint"] = fingerprint
            _state["checked_at"] = now
    return _state["version"]


def stamp_asset_urls(body: bytes, version: str | None = None) -> bytes:
    if b"/static/" not in body:
        return body
    stamp = b"?v=" + (version or asset_version()).encode()
    return _ASSET_URL_RE.sub(lambda match: match.group(1) + stamp, body)
