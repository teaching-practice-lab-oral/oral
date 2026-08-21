import asyncio
import io
import logging
import secrets
import string
import uuid
from datetime import timedelta
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Path, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from app.auth import get_current_admin, verify_admin_password_or_raise, hash_password
from app.config import settings
from app.database import get_db, SessionLocal
from app.models import (
    User, Assignment, Submission, ApiUsageLog, CostlyActionUsageLog, LoginEvent, ActiveSession,
    StudentPresence, EmailJob, AssignmentReminder,
)
from app.schemas import (
    UserCreate, UserUpdate, UserResponse, UserListResponse,
    AdminDashboardStats,
    ImportSummary, ImportedUserDetail, SendImportEmailsRequest,
    ResetPasswordRequest, DeleteConfirmRequest,
    DeliveryJobStartResponse, DeliveryJobStatusResponse, UserMailActionResponse,
)
from app.services import mail
from app.services.admin_audit import log_admin_action, snapshot_user, summarize_imported_users
from app.services.admin_scope import (
    apply_student_visibility_filter,
    apply_user_visibility_filter,
    ensure_admin_can_access_user,
    ensure_admin_can_assign_course_num,
    assignment_visible_to_admin,
    ensure_privileged_admin,
    is_privileged_admin,
    normalize_course_num,
)
from app.services.xlsx import append_xlsx_row
from app.services.import_credentials import (
    issue_import_credential_proof,
    verify_import_credential_proof,
)
from app.services.input_validator import normalize_http_text, normalize_user_text
from app.services.submission_assets import (
    enqueue_submission_asset_cleanup,
    list_submission_asset_refs,
    process_object_deletion_queue_async,
)
from app.utils import taipei_now

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

MAX_IMPORT_XLSX_BYTES = 6 * 1024 * 1024
MAX_IMPORT_XLSX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_IMPORT_XLSX_MEMBER_BYTES = 20 * 1024 * 1024
MAX_IMPORT_XLSX_MEMBERS = 100
# Matches the deployment's supported concurrent-student scale and keeps a
# single synchronous request within a practical reverse-proxy time budget.
MAX_IMPORT_ROWS = 200
MAX_IMPORT_COLUMNS = 5
MAX_IMPORT_SCAN_ROWS = MAX_IMPORT_ROWS + 1  # one header row plus data
_import_capacity = asyncio.Semaphore(2)
_import_guard = asyncio.Lock()
_active_import_admin_ids: set[int] = set()
_IMPORT_ADVISORY_LOCK_KEY = 7_681_000_001


def _generate_password(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _validate_xlsx_archive(content: bytes) -> None:
    """Bound XLSX ZIP expansion before openpyxl reads shared strings/XML."""
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > MAX_IMPORT_XLSX_MEMBERS:
                raise HTTPException(status_code=400, detail="XLSX 內含過多檔案，請重新匯出後再上傳。")
            expanded = 0
            for member in members:
                if member.file_size > MAX_IMPORT_XLSX_MEMBER_BYTES:
                    raise HTTPException(status_code=413, detail="XLSX 解壓後內容過大，請縮小資料量。")
                expanded += member.file_size
                if expanded > MAX_IMPORT_XLSX_EXPANDED_BYTES:
                    raise HTTPException(status_code=413, detail="XLSX 解壓後內容過大，請縮小資料量。")
    except BadZipFile:
        raise HTTPException(status_code=400, detail="匯入檔案格式不正確，請上傳有效的 XLSX 檔案。")


def _validate_xlsx_dimensions(ws) -> None:
    """Reject sparse sheets whose declared grid would make read-only iteration expensive."""
    if (ws.max_row or 0) > MAX_IMPORT_SCAN_ROWS or (ws.max_column or 0) > MAX_IMPORT_COLUMNS:
        raise HTTPException(
            status_code=400,
            detail=f"XLSX 僅可使用 A:E 欄，且一次最多匯入 {MAX_IMPORT_ROWS} 筆學生資料。",
        )


def _append_xlsx_text_row(ws, values: list[object]) -> None:
    """Write external values as literal strings, never spreadsheet formulas."""
    append_xlsx_row(ws, values, force_text=True)


def _acquire_cross_worker_import_lock(db: Session):
    """Use a dedicated Postgres advisory-lock connection across the whole job."""
    engine = db.get_bind()
    if engine.dialect.name != "postgresql":
        return None
    connection = engine.connect()
    acquired = connection.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": _IMPORT_ADVISORY_LOCK_KEY},
    ).scalar()
    if not acquired:
        connection.close()
        raise HTTPException(status_code=429, detail="目前已有匯入作業正在處理，請稍後再試。")
    return connection


def _release_cross_worker_import_lock(connection) -> None:
    if connection is None:
        return
    try:
        connection.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": _IMPORT_ADVISORY_LOCK_KEY},
        )
    finally:
        connection.close()

def _ensure_can_disable_user(admin: User, user: User) -> None:
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="無法停用自己的帳號")
    if user.student_id == settings.PROTECTED_ADMIN_STUDENT_ID:
        raise HTTPException(status_code=403, detail="此帳號不允許被停用")
    if user.role == "admin":
        ensure_privileged_admin(admin, "只有指定管理員可管理管理員帳號")
    if user.role == "student" and not is_privileged_admin(admin):
        raise HTTPException(status_code=403, detail="只有指定管理員可停用學生帳號")


def _ensure_can_delete_user(admin: User, user: User) -> None:
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="無法刪除自己的帳號")
    if user.student_id == settings.PROTECTED_ADMIN_STUDENT_ID:
        raise HTTPException(status_code=403, detail="此帳號不允許被刪除")
    if user.role == "admin":
        ensure_privileged_admin(admin, "只有指定管理員可管理管理員帳號")
    if user.role == "student" and not is_privileged_admin(admin):
        raise HTTPException(status_code=403, detail="只有指定管理員可刪除學生帳號")


def _ensure_protected_admin_course_num(user: User, course_num: str | None) -> None:
    if user.student_id == settings.PROTECTED_ADMIN_STUDENT_ID and normalize_course_num(course_num) is not None:
        raise HTTPException(status_code=403, detail="受保護管理員不可被指定課號")


def _validate_imported_user_batch(
    users: list[ImportedUserDetail],
    admin: User,
    db: Session,
) -> list[ImportedUserDetail]:
    """Bind client-held import credentials back to real, recent users in scope."""
    user_ids = [item.user_id for item in users]
    if len(set(user_ids)) != len(user_ids):
        raise HTTPException(status_code=400, detail="匯入帳號清單包含重複使用者")

    rows = db.query(User).filter(User.id.in_(user_ids)).all()
    rows_by_id = {row.id: row for row in rows}
    cutoff = taipei_now() - timedelta(hours=24)
    validated: list[ImportedUserDetail] = []
    for item in users:
        user = rows_by_id.get(item.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=f"找不到使用者：{item.user_id}")
        ensure_admin_can_access_user(admin, user)
        if user.role != "student":
            raise HTTPException(status_code=400, detail="匯入帳號清單只能包含學生帳號")
        if user.created_at < cutoff or not user.must_change_password:
            raise HTTPException(status_code=400, detail="匯入帳號憑證已過期，請重新匯入或重設密碼")
        if not verify_import_credential_proof(item.user_id, item.password, item.credential_proof):
            raise HTTPException(status_code=400, detail="匯入帳號憑證驗證失敗，請重新匯入")
        if (
            user.student_id != item.student_id
            or user.name != item.name
            or user.email != str(item.email)
            or (user.backup_email or "") != (str(item.backup_email) if item.backup_email else "")
            or normalize_course_num(user.course_num) != normalize_course_num(item.course_num)
        ):
            raise HTTPException(status_code=400, detail="匯入帳號清單與伺服器資料不一致，請重新整理後再試")
        validated.append(item)
    return validated


def _get_account_email_job_for_admin(
    db: Session,
    admin: User,
    job_id: str,
) -> EmailJob:
    """Return an account-delivery job only to its creator or protected admin."""
    job = (
        db.query(EmailJob)
        .filter(
            EmailJob.id == job_id,
            EmailJob.kind == "account",
        )
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Email job not found")
    if job.created_by_id != admin.id and not is_privileged_admin(admin):
        # Do not reveal whether another administrator's unguessable job ID is valid.
        raise HTTPException(status_code=404, detail="Email job not found")
    return job


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=AdminDashboardStats)
def dashboard(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    visible_students = apply_student_visibility_filter(db.query(User), admin).all()
    visible_student_ids = [student.id for student in visible_students]
    visible_assignments = [
        assignment
        for assignment in db.query(Assignment).all()
        if assignment_visible_to_admin(admin, assignment)
    ]
    visible_assignment_ids = [assignment.id for assignment in visible_assignments]

    total_students = len(visible_students)
    total_assignments = len(visible_assignments)
    total_submissions = (
        db.query(Submission)
        .filter(
            Submission.user_id.in_(visible_student_ids) if visible_student_ids else False,
            Submission.assignment_id.in_(visible_assignment_ids) if visible_assignment_ids else False,
        )
        .count()
        if visible_student_ids and visible_assignment_ids
        else 0
    )
    completed_submissions = db.query(Submission).filter(
        Submission.submitted_at.isnot(None),
        Submission.user_id.in_(visible_student_ids) if visible_student_ids else False,
        Submission.assignment_id.in_(visible_assignment_ids) if visible_assignment_ids else False,
    ).count() if visible_student_ids and visible_assignment_ids else 0
    today_start = taipei_now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_api_calls = db.query(ApiUsageLog).filter(
        ApiUsageLog.called_at >= today_start,
        ApiUsageLog.user_id.in_(visible_student_ids) if visible_student_ids else False,
    ).count() if visible_student_ids else 0
    return AdminDashboardStats(
        total_students=total_students,
        total_assignments=total_assignments,
        total_submissions=total_submissions,
        completed_submissions=completed_submissions,
        today_api_calls=today_api_calls,
    )


# ── Classes ───────────────────────────────────────────────────────────────────

@router.get("/classes")
def list_classes(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    rows = (
        apply_student_visibility_filter(db.query(User.course_num), admin)
        .filter(User.course_num.isnot(None))
        .distinct()
        .order_by(User.course_num)
        .all()
    )
    return [r[0] for r in rows]


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=UserListResponse)
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    course_num: str = Query(None, max_length=64),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    course_num = normalize_http_text(course_num, field_name="course_num")
    query = apply_user_visibility_filter(db.query(User), admin)
    if course_num:
        query = query.filter(User.course_num == course_num)
    total = query.count()
    users = query.offset(skip).limit(limit).all()
    return UserListResponse(total=total, users=[UserResponse.model_validate(u) for u in users])


@router.post("/users", response_model=UserMailActionResponse, status_code=201)
async def create_user(
    payload: UserCreate,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.student_id == payload.student_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Student ID already exists")
    if payload.role == "admin":
        ensure_privileged_admin(admin, "只有指定管理員可建立管理員帳號")
        if payload.backup_email is not None:
            raise HTTPException(status_code=400, detail="僅學生帳號可設定備用信箱")
    ensure_admin_can_assign_course_num(admin, payload.course_num)
    user = User(
        student_id=payload.student_id,
        name=payload.name,
        email=str(payload.email),
        backup_email=str(payload.backup_email) if payload.backup_email else None,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        course_num=payload.course_num or None,
        is_active=True,
        must_change_password=True,
    )
    _ensure_protected_admin_course_num(user, payload.course_num)
    db.add(user)
    db.flush()
    log_admin_action(
        db,
        admin,
        "admin.user.create",
        request=request,
        target_type="user",
        target_id=user.id,
        target_label=user.student_id,
        after=snapshot_user(user),
        summary=f"建立 {user.role} 帳號 {user.student_id}",
    )
    db.commit()
    db.refresh(user)
    try:
        await mail.send_password_email(
            user.email, user.name, user.student_id, payload.password, user.backup_email,
        )
    except Exception:
        logger.exception("Failed to send account email to user id=%s", user.id)
        return UserMailActionResponse(
            message="使用者已建立，但帳號通知信寄送失敗，請稍後再試或改用重設密碼功能補寄。",
            email_sent=False,
        )
    return UserMailActionResponse(message="使用者建立成功，已寄送帳號通知信。")


@router.post("/users/import", response_model=ImportSummary)
async def import_users(
    request: Request,
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    try:
        original_filename = normalize_user_text(file.filename or "xlsx-import", field_name="匯入檔名")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not original_filename or len(original_filename) > 256:
        raise HTTPException(status_code=422, detail="匯入檔名不可為空且不得超過 256 個字元。")
    content = await file.read(MAX_IMPORT_XLSX_BYTES + 1)
    if len(content) > MAX_IMPORT_XLSX_BYTES:
        raise HTTPException(status_code=413, detail="匯入檔案過大，上限為 6 MiB。")
    _validate_xlsx_archive(content)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, OSError, ValueError):
        raise HTTPException(status_code=400, detail="匯入檔案格式不正確，請上傳有效的 XLSX 檔案。")
    ws = wb.active
    try:
        _validate_xlsx_dimensions(ws)
    except HTTPException:
        wb.close()
        raise

    async with _import_guard:
        if admin.id in _active_import_admin_ids:
            wb.close()
            raise HTTPException(status_code=429, detail="您已有一個匯入作業正在處理，請完成後再試。")
        _active_import_admin_ids.add(admin.id)

    advisory_connection = None
    try:
        advisory_connection = _acquire_cross_worker_import_lock(db)
        async with _import_capacity:
            created = 0
            skipped = 0
            errors = []
            imported_users: list[ImportedUserDetail] = []
            data_rows = 0

            for row_idx, row in enumerate(
                ws.iter_rows(
                    min_row=2,
                    max_row=MAX_IMPORT_SCAN_ROWS,
                    max_col=MAX_IMPORT_COLUMNS,
                    values_only=True,
                ),
                start=2,
            ):
                if not row or all(v is None for v in row):
                    continue
                data_rows += 1
                if data_rows > MAX_IMPORT_ROWS:
                    db.rollback()
                    raise HTTPException(
                        status_code=400,
                        detail=f"一次最多匯入 {MAX_IMPORT_ROWS} 筆學生資料，請分批上傳。",
                    )
                try:
                    student_id = str(row[0]).strip() if row[0] is not None else ""
                    name = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
                    email = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ""
                    course_num = str(row[3]).strip() if len(row) > 3 and row[3] is not None else None
                    backup_email = str(row[4]).strip() if len(row) > 4 and row[4] is not None else None
                    course_num = course_num or None
                    backup_email = backup_email or None

                    if not student_id or not name or not email:
                        errors.append(f"第 {row_idx} 列：學號、姓名與電子郵件不可空白")
                        skipped += 1
                        continue

                    password = _generate_password()
                    validated_input = UserCreate(
                        student_id=student_id,
                        name=name,
                        email=email,
                        backup_email=backup_email,
                        password=password,
                        role="student",
                        course_num=course_num,
                    )
                    student_id = validated_input.student_id
                    name = validated_input.name
                    email = str(validated_input.email)
                    backup_email = (
                        str(validated_input.backup_email)
                        if validated_input.backup_email
                        else None
                    )
                    course_num = validated_input.course_num
                    ensure_admin_can_assign_course_num(admin, course_num)

                    existing = db.query(User).filter(User.student_id == student_id).first()
                    if existing:
                        skipped += 1
                        continue

                    # bcrypt is deliberately off the event-loop thread.  The
                    # module semaphore caps total concurrent import CPU work.
                    hashed_password = await asyncio.to_thread(hash_password, password)
                    with db.begin_nested():
                        user = User(
                            student_id=student_id,
                            name=name,
                            email=email,
                            backup_email=backup_email,
                            hashed_password=hashed_password,
                            role="student",
                            course_num=course_num,
                            is_active=True,
                            must_change_password=True,
                        )
                        db.add(user)
                        db.flush()
                        imported_detail = ImportedUserDetail(
                            user_id=user.id,
                            student_id=student_id,
                            name=name,
                            email=email,
                            backup_email=backup_email,
                            password=password,
                            credential_proof=issue_import_credential_proof(user.id, password),
                            course_num=course_num,
                        )
                    imported_users.append(imported_detail)
                    created += 1
                except HTTPException:
                    raise
                except Exception as e:
                    errors.append(f"第 {row_idx} 列：{e}")
                    skipped += 1

            db.commit()
    finally:
        wb.close()
        _release_cross_worker_import_lock(advisory_connection)
        async with _import_guard:
            _active_import_admin_ids.discard(admin.id)
    log_admin_action(
        db,
        admin,
        "admin.user.import_xlsx",
        request=request,
        target_type="user_batch",
        target_label=original_filename,
        summary=f"匯入 XLSX 使用者：建立 {created} 筆，略過 {skipped} 筆",
        details={
            "filename": original_filename,
            "created": created,
            "skipped": skipped,
            "error_count": len(errors),
            "errors": errors[:20],
            "imported_users": summarize_imported_users(imported_users),
        },
    )
    db.commit()
    return ImportSummary(
        total=created + skipped,
        created=created,
        skipped=skipped,
        errors=errors,
        imported_users=imported_users,
    )


# Bounded fan-out + per-message retry. Outlook throttles bursts of concurrent logins,
# so we keep concurrency low and back off on failure rather than hammering. With a
# batch of 150+ this runs for minutes — far past the ~100s Cloudflare/gunicorn request
# window — so it MUST run in the background, not inline with the HTTP response.
_EMAIL_CONCURRENCY = 2
_EMAIL_MAX_ATTEMPTS = 3
_EMAIL_RETRY_BACKOFF = 2.0  # seconds, multiplied by attempt number
_EMAIL_PACE = 0.4           # small gap after each send to ease Outlook rate limits


async def _run_email_job(job_id: str, users: list[ImportedUserDetail]) -> None:
    """Background worker: send every account email, recording progress to EmailJob."""
    sem = asyncio.Semaphore(_EMAIL_CONCURRENCY)
    db = SessionLocal()
    sent = 0
    failed_emails: list[str] = []

    job = db.get(EmailJob, job_id)
    if job is not None:
        job.state = "running"
        db.commit()

    async def _send_one(u: ImportedUserDetail) -> str | None:
        async with sem:
            for attempt in range(1, _EMAIL_MAX_ATTEMPTS + 1):
                try:
                    await mail.send_password_email(
                        str(u.email), u.name, u.student_id, u.password,
                        str(u.backup_email) if u.backup_email else None,
                    )
                    await asyncio.sleep(_EMAIL_PACE)
                    return None
                except Exception:
                    if attempt < _EMAIL_MAX_ATTEMPTS:
                        await asyncio.sleep(_EMAIL_RETRY_BACKOFF * attempt)
                        continue
                    logger.exception(
                        "Failed to send account email to %s (student_id=%s) after %d attempts",
                        u.email, u.student_id, _EMAIL_MAX_ATTEMPTS,
                    )
                    return u.email
        return u.email

    try:
        tasks = [asyncio.create_task(_send_one(u)) for u in users]
        for fut in asyncio.as_completed(tasks):
            failure = await fut
            if failure:
                failed_emails.append(failure)
            else:
                sent += 1
            job = db.get(EmailJob, job_id)
            if job is not None:
                job.processed = sent + len(failed_emails)
                job.succeeded = sent
                job.failed = len(failed_emails)
                job.details = {"failed_emails": list(failed_emails)}
                db.commit()
        job = db.get(EmailJob, job_id)
        if job is not None:
            job.processed = sent + len(failed_emails)
            job.succeeded = sent
            job.failed = len(failed_emails)
            job.details = {"failed_emails": list(failed_emails)}
            job.state = "completed"
            job.completed_at = taipei_now()
            db.commit()
        logger.info("send-import-emails job %s done: %d sent, %d failed", job_id, sent, len(failed_emails))
    except Exception:
        logger.exception("Email job %s crashed", job_id)
        try:
            job = db.get(EmailJob, job_id)
            if job is not None:
                job.state = "failed"
                job.error = "帳號通知寄送工作意外中止"
                job.completed_at = taipei_now()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/users/send-import-emails", response_model=DeliveryJobStartResponse)
async def send_import_emails(
    payload: SendImportEmailsRequest,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    users = _validate_imported_user_batch(payload.users, admin, db)
    job_id = uuid.uuid4().hex
    job = EmailJob(
        id=job_id,
        kind="account",
        created_by_id=admin.id,
        state="queued",
        total=len(users),
        details={"failed_emails": []},
    )
    db.add(job)
    db.commit()
    log_admin_action(
        db,
        admin,
        "admin.user.send_import_emails",
        request=request,
        target_type="email_job",
        target_id=job_id,
        target_label="import-account-emails",
        summary=f"啟動匯入帳號通知信寄送，共 {len(users)} 筆",
        details={
            "job_id": job_id,
            "total": len(users),
            "users": summarize_imported_users(users),
        },
    )
    db.commit()
    # Fire-and-forget: the task keeps the user list in this worker's memory and writes
    # progress to the DB, which the status endpoint reads back (possibly from another worker).
    asyncio.create_task(_run_email_job(job_id, list(users)))
    return DeliveryJobStartResponse(job_id=job_id, total=len(users), state="queued")


@router.get("/users/send-import-emails/{job_id}", response_model=DeliveryJobStatusResponse)
def get_email_job_status(
    job_id: str = Path(min_length=1, max_length=64),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    job_id = normalize_http_text(job_id, field_name="job_id") or ""
    job = _get_account_email_job_for_admin(db, admin, job_id)
    return DeliveryJobStatusResponse(
        job_id=job.id,
        kind=job.kind,
        state=job.state,
        total=job.total,
        processed=job.processed,
        succeeded=job.succeeded,
        failed=job.failed,
        details=job.details or {},
        error=job.error,
    )


@router.post("/users/export-batch-xlsx")
async def export_batch_xlsx(
    payload: SendImportEmailsRequest,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    users = _validate_imported_user_batch(payload.users, admin, db)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "批次建立帳號"
    ws.append(["學號", "姓名", "電子郵件", "課號", "備用信箱", "初始密碼"])
    for u in users:
        _append_xlsx_text_row(ws, [
            u.student_id, u.name, str(u.email), u.course_num or "",
            str(u.backup_email) if u.backup_email else "", u.password,
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    imported_summary = summarize_imported_users(users)
    imported_summary["includes_passwords"] = True
    log_admin_action(
        db,
        admin,
        "admin.user.export_batch_xlsx",
        request=request,
        target_type="user_batch_export",
        target_label="imported_accounts.xlsx",
        summary=f"匯出匯入帳號 XLSX，共 {len(users)} 筆",
        details=imported_summary,
    )
    db.commit()
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="imported_accounts.xlsx"'},
    )


@router.post("/users/{user_id}/reset-password", response_model=UserMailActionResponse)
async def reset_password(
    user_id: int,
    payload: ResetPasswordRequest,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    verify_admin_password_or_raise(admin, payload.admin_password, "重設密碼操作")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    ensure_admin_can_access_user(admin, user)
    if user.role == "admin" and user.id != admin.id:
        ensure_privileged_admin(admin, "只有指定管理員可管理管理員帳號")
    if user.student_id == settings.PROTECTED_ADMIN_STUDENT_ID and user.id != admin.id:
        raise HTTPException(status_code=403, detail="不可直接重設受保護管理員的密碼")
    before = snapshot_user(user)
    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = True
    # Password reset is an account-recovery boundary: every existing browser
    # session for the target must stop working as part of the same transaction.
    # The mail send intentionally stays after commit so SMTP failure cannot undo
    # either the password change or the revocation.
    if user.role != "admin":
        user.session_version = (user.session_version or 0) + 1
    db.query(StudentPresence).filter(StudentPresence.user_id == user.id).delete(
        synchronize_session=False,
    )
    db.query(ActiveSession).filter(ActiveSession.user_id == user.id).delete(
        synchronize_session=False,
    )
    log_admin_action(
        db,
        admin,
        "admin.user.reset_password",
        request=request,
        target_type="user",
        target_id=user.id,
        target_label=user.student_id,
        before=before,
        after=snapshot_user(user),
        summary=f"重設使用者密碼：{user.student_id}",
        details={"email": user.email},
    )
    db.commit()
    logger.info("Admin %s (id=%s) reset password for user %s (id=%s)", admin.student_id, admin.id, user.student_id, user.id)
    # Notify the user of their new password. Mail failures must not fail the reset
    # itself — the password has already been changed and committed above.
    try:
        await mail.send_reset_password_email(
            user.email, user.name, payload.new_password, user.backup_email,
        )
    except Exception:
        logger.exception("Failed to send reset-password email to user id=%s", user.id)
        return UserMailActionResponse(
            message="密碼已重設，但通知信寄送失敗，請確認信箱設定後再協助使用者登入。",
            email_sent=False,
        )
    return UserMailActionResponse(message="密碼重設成功，已寄送通知信。")


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    ensure_admin_can_access_user(admin, user)
    if user.role == "admin" and user.id != admin.id:
        ensure_privileged_admin(admin, "只有指定管理員可管理管理員帳號")
    before = snapshot_user(user)
    if payload.role is not None and payload.role != user.role:
        raise HTTPException(status_code=403, detail="不允許變更使用者角色")
    if payload.is_active is not None:
        if not payload.is_active:
            _ensure_can_disable_user(admin, user)
        user.is_active = payload.is_active
    if payload.name is not None:
        user.name = payload.name
    if payload.email is not None:
        user.email = str(payload.email)
    if "backup_email" in payload.model_fields_set:
        if user.role != "student":
            raise HTTPException(status_code=400, detail="僅學生帳號可設定備用信箱")
        user.backup_email = str(payload.backup_email) if payload.backup_email else None
    if "course_num" in payload.model_fields_set:
        ensure_admin_can_assign_course_num(admin, payload.course_num)
        _ensure_protected_admin_course_num(user, payload.course_num)
        user.course_num = payload.course_num or None
    log_admin_action(
        db,
        admin,
        "admin.user.update",
        request=request,
        target_type="user",
        target_id=user.id,
        target_label=user.student_id,
        before=before,
        after=snapshot_user(user),
        summary=f"更新使用者資料：{user.student_id}",
    )
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


@router.post("/users/{user_id}/delete", status_code=204)
def delete_user_confirmed(
    user_id: int,
    payload: DeleteConfirmRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    verify_admin_password_or_raise(admin, payload.admin_password, "刪除操作")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    ensure_admin_can_access_user(admin, user)
    _ensure_can_delete_user(admin, user)
    before = snapshot_user(user)
    asset_refs = list_submission_asset_refs(db, user_id=user.id)
    queued_prefixes = enqueue_submission_asset_cleanup(db, asset_refs)
    logger.warning("Admin %s (id=%s) deleted user '%s' (id=%s, role=%s)", admin.student_id, admin.id, user.student_id, user.id, user.role)
    db.query(LoginEvent).filter(LoginEvent.user_id == user.id).update({"user_id": None})
    db.query(ActiveSession).filter(ActiveSession.user_id == user.id).delete()
    db.query(ApiUsageLog).filter(ApiUsageLog.user_id == user.id).delete()
    db.query(CostlyActionUsageLog).filter(CostlyActionUsageLog.user_id == user.id).delete()
    db.query(AssignmentReminder).filter(AssignmentReminder.user_id == user.id).delete()
    db.query(Submission).filter(Submission.user_id == user.id).delete()
    log_admin_action(
        db,
        admin,
        "admin.user.delete",
        request=request,
        target_type="user",
        target_id=user.id,
        target_label=user.student_id,
        before=before,
        summary=f"刪除使用者：{user.student_id}",
        details={"queued_object_prefixes": queued_prefixes},
    )
    db.delete(user)
    db.commit()
    background_tasks.add_task(process_object_deletion_queue_async)
