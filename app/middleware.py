"""Small ASGI security middleware that must run before request parsing."""

import re

from starlette.responses import JSONResponse


class _RequestBodyTooLarge(Exception):
    pass


KIB = 1024
MIB = 1024 * KIB
AUTH_BODY_LIMIT = 16 * KIB
STUDENT_TEXT_BODY_LIMIT = 64 * KIB
PROCTOR_BODY_LIMIT = 4 * KIB
REFLECTION_PHOTO_BODY_LIMIT = 11 * MIB
AUDIO_BODY_LIMIT = 52 * MIB
ADMIN_IMPORT_BODY_LIMIT = 6 * MIB
ADMIN_JSON_BODY_LIMIT = 1 * MIB

_STUDENT_AUDIO_PATH_RE = re.compile(
    r"^/api/student/submissions/\d+/(?:speaking1/\d+|roleplay/turn)$"
)
_REFLECTION_PHOTO_PATH_RE = re.compile(
    r"^/api/student/submissions/\d+/reflection/photo$"
)
_PROCTOR_PATH_RE = re.compile(
    r"^/api/student/submissions/\d+/proctor-events$"
)


def request_body_limit_for_scope(scope, configured_max: int) -> int:
    """Choose a pre-parser body cap for the concrete application surface."""
    path = scope.get("path", "")
    method = scope.get("method", "GET").upper()
    if method in {"GET", "HEAD", "OPTIONS"}:
        return configured_max
    if path.startswith("/api/auth/"):
        route_limit = AUTH_BODY_LIMIT
    elif _STUDENT_AUDIO_PATH_RE.fullmatch(path):
        route_limit = AUDIO_BODY_LIMIT
    elif _REFLECTION_PHOTO_PATH_RE.fullmatch(path):
        route_limit = REFLECTION_PHOTO_BODY_LIMIT
    elif _PROCTOR_PATH_RE.fullmatch(path):
        route_limit = PROCTOR_BODY_LIMIT
    elif path.startswith("/api/student/"):
        route_limit = STUDENT_TEXT_BODY_LIMIT
    elif path == "/api/admin/users/import":
        route_limit = ADMIN_IMPORT_BODY_LIMIT
    elif path.startswith("/api/admin/"):
        route_limit = ADMIN_JSON_BODY_LIMIT
    else:
        route_limit = configured_max
    return min(configured_max, route_limit)


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP bodies, including chunked bodies.

    Endpoint-level ``UploadFile.read`` checks run too late to protect the
    multipart parser.  Wrapping ASGI ``receive`` puts the cap in front of
    Starlette/FastAPI form parsing.
    """

    def __init__(self, app, max_body_size: int):
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        body_limit = request_body_limit_for_scope(scope, self.max_body_size)
        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                declared_length = int(content_length)
                if declared_length < 0 or declared_length > body_limit:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                await self._reject(scope, receive, send)
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > body_limit:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope, receive, send):
        response = JSONResponse(
            {"detail": "上傳內容過大，請縮小檔案後再試。"},
            status_code=413,
        )
        await response(scope, receive, send)
