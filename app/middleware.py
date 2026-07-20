"""Small ASGI security middleware that must run before request parsing."""

import secrets

from starlette.responses import JSONResponse


class _RequestBodyTooLarge(Exception):
    pass


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

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_body_size:
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
                if received > self.max_body_size:
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


class BearerPathAuthMiddleware:
    """Reject protected paths from headers before the application reads a body."""

    def __init__(self, app, *, path_prefix: str, secret):
        self.app = app
        self.path_prefix = path_prefix
        self.secret = secret

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith(self.path_prefix):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        supplied = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
        if not supplied:
            response = JSONResponse({"detail": "Worker token required or invalid"}, status_code=401)
            await response(scope, receive, send)
            return
        configured_secret = self.secret() if callable(self.secret) else self.secret
        if not configured_secret:
            response = JSONResponse({"detail": "Worker secret is not configured"}, status_code=503)
            await response(scope, receive, send)
            return
        if not secrets.compare_digest(supplied, configured_secret):
            response = JSONResponse({"detail": "Worker token required or invalid"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
