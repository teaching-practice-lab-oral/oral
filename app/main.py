import asyncio
import secrets
from contextlib import asynccontextmanager
from html import escape

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
import os

from app.auth import decode_token
from app.config import settings
from app.routers import auth, student, admin, workflow, result_downloads
from app.services.maintenance import maintenance_scheduler_loop
from app.services.reminders import reminder_scheduler_loop
from app.middleware import RequestBodyLimitMiddleware

if settings.WORKER_ONLY:
    raise RuntimeError("WORKER_ONLY=true must run app.worker_main:app, not app.main:app")

_CSRF_EXEMPT = {"/api/auth/login", "/api/auth/refresh", "/api/auth/logout"}
_CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Each worker starts this loop, but a Postgres advisory lock inside ensures only one
    # actually runs the deadline-reminder scan each hour.
    tasks = [
        asyncio.create_task(reminder_scheduler_loop()),
        asyncio.create_task(maintenance_scheduler_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()


app = FastAPI(
    title="English Interview Practice System",
    description="AI-assisted English interview practice for university students",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# Reject malformed/unexpected Host headers and oversized bodies before URL
# reconstruction or multipart parsing can occur.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts_list)
app.add_middleware(RequestBodyLimitMiddleware, max_body_size=settings.MAX_REQUEST_BODY_BYTES)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-CSRF-Token"],
)


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    request_path = request.scope.get("path", "")
    if (
        request.method not in _CSRF_SAFE_METHODS
        and request_path.startswith("/api/")
        and request_path not in _CSRF_EXEMPT
    ):
        csrf_cookie = request.cookies.get("csrf_token", "")
        csrf_header = request.headers.get("X-CSRF-Token", "")
        if not csrf_cookie or not secrets.compare_digest(csrf_cookie, csrf_header):
            return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)
    return await call_next(request)


_ACTION_DELEGATOR_TAG = b'<script type="module" src="/static/js/action-delegator.mjs?v=1"></script>'


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    nonce = secrets.token_urlsafe(16)
    response: Response = await call_next(request)

    # For HTML, load the action delegator and stamp every <script> with the CSP
    # nonce (so inline scripts run under a strict no-'unsafe-inline' policy) plus
    # data-cfasync="false" (so Cloudflare Rocket Loader leaves nonced scripts intact).
    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type and hasattr(response, "body_iterator"):
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        if b"</head>" in body:
            body = body.replace(b"</head>", _ACTION_DELEGATOR_TAG + b"</head>", 1)
        else:
            body = _ACTION_DELEGATOR_TAG + body
        body = body.replace(b"<script", b'<script nonce="' + nonce.encode() + b'" data-cfasync="false"')
        response = Response(
            content=body,
            status_code=response.status_code,
            media_type="text/html",
            headers={k: v for k, v in response.headers.items()
                     if k.lower() not in ("content-length", "content-security-policy")},
        )

    if not request.cookies.get("csrf_token"):
        response.set_cookie(
            "csrf_token",
            secrets.token_hex(32),
            httponly=False,
            secure=settings.APP_ENV == "production",
            samesite="strict",
            max_age=86400,
        )
    practice_shell_page = request.url.path.startswith("/student/assignment/")
    frame_ancestors = "'self'" if practice_shell_page else "'none'"
    frame_sources = "'self' https://challenges.cloudflare.com" if practice_shell_page else "https://challenges.cloudflare.com"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN" if practice_shell_page else "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(self)"
    # Strict script CSP: no 'unsafe-inline'. Inline scripts are allowed via the per-request
    # nonce injected above; inline event handlers were removed in favour of the delegation
    # action delegator. style-src keeps 'unsafe-inline' (inline styles remain).
    response.headers["Content-Security-Policy"] = (
        f"default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net https://challenges.cloudflare.com; "
        f"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        f"font-src 'self' https://cdn.jsdelivr.net; "
        f"img-src 'self' data: https://*.oraclecloud.com; "
        f"media-src 'self' blob: https://*.oraclecloud.com; "
        f"connect-src 'self' https://challenges.cloudflare.com; "
        f"frame-src {frame_sources}; "
        f"frame-ancestors {frame_ancestors}; "
        f"object-src 'none'; "
        f"base-uri 'self'"
    )
    if settings.APP_ENV == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# GZip must be the OUTERMOST middleware so it compresses the final body *after*
# add_security_headers has rewritten the HTML (CSP nonce/action-module injection). Added
# last → registered first in the stack → runs last on the response path.
app.add_middleware(GZipMiddleware, minimum_size=500)

# API Routers
app.include_router(auth.router)
app.include_router(student.router)
app.include_router(admin.router)
app.include_router(workflow.router)
app.include_router(result_downloads.router)

class CachedStaticFiles(StaticFiles):
    """StaticFiles that lets browsers cache assets for an hour instead of
    re-validating (304 round-trip) on every page navigation. Asset URLs are not
    yet content-hashed, so max-age is kept modest; after a deploy a stale asset
    is served for at most an hour. ETag/Last-Modified revalidation still applies."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response


# Static files (CSS/JS assets if any)
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", CachedStaticFiles(directory=static_dir), name="static")


# ── Page Routes ───────────────────────────────────────────────────────────────

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(os.path.join(static_dir, "favicon.svg"), media_type="image/svg+xml")


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def apple_touch_icon():
    return FileResponse(
        os.path.join(static_dir, "icons", "apple-touch-icon-v2.png"),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/manifest.webmanifest", include_in_schema=False)
def web_app_manifest():
    return FileResponse(
        os.path.join(static_dir, "manifest.webmanifest"),
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(
        os.path.join(static_dir, "sw.js"),
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )

def _admin_redirect(request: Request) -> RedirectResponse | None:
    """Return a redirect to /admin if the requester is an admin, else None."""
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = decode_token(token)
            if payload.get("role") == "admin":
                return RedirectResponse(url="/admin")
        except HTTPException:
            pass
    return None


@app.head("/", include_in_schema=False)
def root_head():
    return Response(status_code=200)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/login")


@app.get("/login", include_in_schema=False)
def login_page():
    with open(os.path.join(static_dir, "login.html"), encoding="utf-8") as f:
        body = f.read()
    body = body.replace("__TURNSTILE_SITE_KEY__", escape(settings.TURNSTILE_SITE_KEY, quote=True))
    return HTMLResponse(body, headers=_NO_CACHE)


@app.get("/reset-password", include_in_schema=False)
def reset_password_page():
    with open(os.path.join(static_dir, "reset-password.html"), encoding="utf-8") as f:
        body = f.read()
    body = body.replace("__TURNSTILE_SITE_KEY__", escape(settings.TURNSTILE_SITE_KEY, quote=True))
    return HTMLResponse(body, headers=_NO_CACHE)


@app.get("/student", include_in_schema=False)
def student_index(request: Request):
    if r := _admin_redirect(request):
        return r
    return FileResponse(os.path.join(static_dir, "student", "index.html"), headers=_NO_CACHE)


@app.get("/student/assignment/{assignment_id}", include_in_schema=False)
def student_assignment(assignment_id: int, request: Request):
    if r := _admin_redirect(request):
        return r
    return RedirectResponse(url=f"/student/assignment/{assignment_id}/job-profile")


@app.get("/student/assignment/{assignment_id}/job-profile", include_in_schema=False)
def student_job_profile(assignment_id: int, request: Request):
    if r := _admin_redirect(request):
        return r
    return FileResponse(os.path.join(static_dir, "student", "job-profile.html"), headers=_NO_CACHE)


@app.get("/student/assignment/{assignment_id}/writing", include_in_schema=False)
def student_writing(assignment_id: int, request: Request):
    if r := _admin_redirect(request):
        return r
    return FileResponse(os.path.join(static_dir, "student", "writing.html"), headers=_NO_CACHE)


@app.get("/student/assignment/{assignment_id}/shadowing", include_in_schema=False)
def student_shadowing(assignment_id: int, request: Request):
    if r := _admin_redirect(request):
        return r
    return FileResponse(os.path.join(static_dir, "student", "shadowing.html"), headers=_NO_CACHE)


@app.get("/student/assignment/{assignment_id}/roleplay", include_in_schema=False)
def student_roleplay(assignment_id: int, request: Request):
    if r := _admin_redirect(request):
        return r
    return FileResponse(os.path.join(static_dir, "student", "roleplay.html"), headers=_NO_CACHE)


@app.get("/student/assignment/{assignment_id}/report", include_in_schema=False)
def student_report(assignment_id: int, request: Request):
    if r := _admin_redirect(request):
        return r
    return FileResponse(os.path.join(static_dir, "student", "report.html"), headers=_NO_CACHE)


@app.get("/student/assignment/{assignment_id}/reflection", include_in_schema=False)
def student_reflection(assignment_id: int, request: Request):
    if r := _admin_redirect(request):
        return r
    return FileResponse(os.path.join(static_dir, "student", "reflection.html"), headers=_NO_CACHE)


_NO_CACHE = {"Cache-Control": "no-store"}


@app.get("/admin", include_in_schema=False)
def admin_index():
    return FileResponse(os.path.join(static_dir, "admin", "index.html"), headers=_NO_CACHE)


@app.get("/admin/users", include_in_schema=False)
def admin_users():
    return FileResponse(os.path.join(static_dir, "admin", "users.html"), headers=_NO_CACHE)


@app.get("/admin/grading", include_in_schema=False)
def admin_grading():
    return FileResponse(os.path.join(static_dir, "admin", "grading.html"), headers=_NO_CACHE)


@app.get("/admin/assignments", include_in_schema=False)
def admin_assignments():
    return FileResponse(os.path.join(static_dir, "admin", "assignments.html"), headers=_NO_CACHE)


@app.get("/admin/assignments/{assignment_id}/results", include_in_schema=False)
def admin_results(assignment_id: int):
    return FileResponse(os.path.join(static_dir, "admin", "results.html"), headers=_NO_CACHE)


@app.get("/admin/assignments/{assignment_id}/students/{user_id}", include_in_schema=False)
def admin_student_detail(assignment_id: int, user_id: int):
    return FileResponse(os.path.join(static_dir, "admin", "student_detail.html"), headers=_NO_CACHE)


@app.get("/admin/create-assignment", include_in_schema=False)
def admin_create_assignment():
    return FileResponse(os.path.join(static_dir, "admin", "create-assignment.html"), headers=_NO_CACHE)


@app.get("/admin/rubrics", include_in_schema=False)
def admin_rubrics():
    return FileResponse(os.path.join(static_dir, "admin", "rubrics.html"), headers=_NO_CACHE)


@app.get("/admin/assignments/{assignment_id}/edit", include_in_schema=False)
def admin_edit_assignment(assignment_id: int):
    return FileResponse(os.path.join(static_dir, "admin", "edit-assignment.html"), headers=_NO_CACHE)


@app.get("/admin/login-audit", include_in_schema=False)
def admin_login_audit():
    return FileResponse(os.path.join(static_dir, "admin", "login-audit.html"), headers=_NO_CACHE)
