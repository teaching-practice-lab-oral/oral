import io
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, load_only

from app.auth import get_current_admin
from app.database import get_db
from app.db_helpers import (
    get_latest_submission,
    load_users_by_ids,
)
from app.models import (
    User,
    Submission,
)
from app.services.export_builders import _build_submission_docx, _build_submission_audio_zip
from app.services.assignment_grade_export import (
    _build_assignment_grade_workbook,
    _get_visible_students_for_assignment,
    _hydrate_for_export,
    _latest_submissions_by_user,
    _safe_assignment_grade_filename,
)
from app.services.admin_audit import log_admin_action
from app.services.admin_scope import ensure_admin_can_access_student_assignment
from app.services.grading import latest_grades_by_submission
from app.services.admin_submission_access import (
    get_accessible_assignment as _get_accessible_assignment,
    get_accessible_submission_context as _get_accessible_submission_context,
)
from app.services.batch_export import BatchExportFailed, build_zip_with_manifest

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.get("/submissions/{submission_id}/export-word")
def export_submission_word(
    submission_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    sub, student, assignment = _get_accessible_submission_context(db, admin, submission_id)

    word_bytes = _build_submission_docx(student, assignment, sub)
    safe_title = (assignment.title if assignment else "作業").translate(str.maketrans('', '', r'/\:*?"<>|'))[:40]
    safe_name = f"{safe_title}_{student.student_id}_第{sub.attempt_number}次.docx"
    log_admin_action(
        db,
        admin,
        "admin.export.submission_word",
        request=request,
        target_type="submission",
        target_id=sub.id,
        target_label=safe_name,
        summary=f"匯出單次提交 Word：{safe_name}",
        details={"assignment_id": sub.assignment_id, "user_id": sub.user_id},
    )
    db.commit()
    return StreamingResponse(
        io.BytesIO(word_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe_name)}"},
    )


@router.get("/submissions/{submission_id}/export-audio")
def export_submission_audio(
    submission_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    sub, student, _ = _get_accessible_submission_context(db, admin, submission_id)

    zip_bytes = _build_submission_audio_zip(student, sub)
    safe_name = f"{student.student_id}_{sub.attempt_number}_audio.zip"
    log_admin_action(
        db,
        admin,
        "admin.export.submission_audio",
        request=request,
        target_type="submission",
        target_id=sub.id,
        target_label=safe_name,
        summary=f"匯出單次提交音檔：{safe_name}",
        details={"assignment_id": sub.assignment_id, "user_id": sub.user_id},
    )
    db.commit()
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


# ── Per-student word exports ──────────────────────────────────────────────────

@router.get("/assignments/{assignment_id}/students/{user_id}/export-words")
def export_student_all_words(
    assignment_id: int,
    user_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    assignment = _get_accessible_assignment(db, admin, assignment_id)
    student = db.query(User).filter(User.id == user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    ensure_admin_can_access_student_assignment(admin, student, assignment)

    submissions = (
        db.query(Submission)
        .filter(
            Submission.user_id == user_id,
            Submission.assignment_id == assignment_id,
            Submission.submitted_at.isnot(None),
        )
        .order_by(Submission.attempt_number.asc())
        .all()
    )

    if not submissions:
        raise HTTPException(status_code=404, detail="沒有已完成的提交可匯出")
    safe_archive_title = assignment.title.translate(str.maketrans('', '', r'/\:*?"<>|'))[:40]

    def render_submission(sub: Submission) -> tuple[str, bytes]:
        _hydrate_for_export(db, sub)
        filename = f"{safe_archive_title}_{student.student_id}_第{sub.attempt_number}次.docx"
        return filename, _build_submission_docx(student, assignment, sub)

    try:
        result = build_zip_with_manifest(
            submissions,
            render=render_submission,
            identity=lambda sub: f"submission {sub.id}",
        )
    except BatchExportFailed as exc:
        raise HTTPException(status_code=500, detail="全部 Word 文件匯出失敗，請檢查資料後重試") from exc

    safe_title = assignment.title.replace(" ", "_")[:40]
    download_name = f"{safe_title}_{student.student_id}_all.zip"
    encoded_filename = quote(download_name)
    log_admin_action(
        db,
        admin,
        "admin.export.student_words_all",
        request=request,
        target_type="student_export",
        target_id=f"{assignment_id}:{user_id}",
        target_label=download_name,
        summary=f"匯出學生全部 Word：{student.student_id}",
        details={
            "assignment_id": assignment_id,
            "user_id": user_id,
            "attempted": result.attempted,
            "exported": result.exported,
            "failures": result.failures,
        },
    )
    db.commit()
    return StreamingResponse(
        io.BytesIO(result.archive),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-Export-Partial": "true" if result.partial else "false",
        },
    )


@router.get("/assignments/{assignment_id}/students/{user_id}/export-words-latest")
def export_student_latest_word(
    assignment_id: int,
    user_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    assignment = _get_accessible_assignment(db, admin, assignment_id)
    student = db.query(User).filter(User.id == user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    ensure_admin_can_access_student_assignment(admin, student, assignment)

    sub = get_latest_submission(db, user_id, assignment_id, submitted_only=True)
    if not sub:
        raise HTTPException(status_code=404, detail="No submitted attempt found")

    _hydrate_for_export(db, sub)
    word_bytes = _build_submission_docx(student, assignment, sub)
    safe_title = assignment.title.translate(str.maketrans('', '', r'/\:*?"<>|'))[:40]
    download_name = f"{safe_title}_{student.student_id}_第{sub.attempt_number}次.docx"
    encoded_filename = quote(download_name)
    log_admin_action(
        db,
        admin,
        "admin.export.student_word_latest",
        request=request,
        target_type="student_export",
        target_id=f"{assignment_id}:{user_id}",
        target_label=download_name,
        summary=f"匯出學生最新 Word：{student.student_id}",
        details={"assignment_id": assignment_id, "user_id": user_id, "submission_id": sub.id},
    )
    db.commit()
    return StreamingResponse(
        io.BytesIO(word_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


# ── Assignment-wide exports ───────────────────────────────────────────────────

@router.get("/assignments/{assignment_id}/export-words-latest")
def export_latest_words(
    assignment_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    assignment = _get_accessible_assignment(db, admin, assignment_id)
    visible_students = _get_visible_students_for_assignment(db, admin, assignment)
    visible_student_ids = [student.id for student in visible_students]

    all_submissions = (
        db.query(Submission)
        .filter(
            Submission.assignment_id == assignment_id,
            Submission.submitted_at.isnot(None),
            Submission.user_id.in_(visible_student_ids) if visible_student_ids else False,
        )
        .order_by(Submission.user_id, Submission.attempt_number.desc())
        .all()
    ) if visible_student_ids else []

    seen = set()
    latest_submissions = []
    for sub in all_submissions:
        if sub.user_id not in seen:
            seen.add(sub.user_id)
            latest_submissions.append(sub)

    users_by_id = load_users_by_ids(db, (s.user_id for s in latest_submissions))

    if not latest_submissions:
        raise HTTPException(status_code=404, detail="沒有已完成的提交可匯出")
    safe_archive_title = assignment.title.translate(str.maketrans('', '', r'/\:*?"<>|'))[:40]

    def render_latest(sub: Submission) -> tuple[str, bytes]:
        student = users_by_id.get(sub.user_id)
        if student is None:
            raise ValueError("student row is missing")
        _hydrate_for_export(db, sub)
        filename = f"{safe_archive_title}_{student.student_id}_第{sub.attempt_number}次.docx"
        return filename, _build_submission_docx(student, assignment, sub)

    try:
        result = build_zip_with_manifest(
            latest_submissions,
            render=render_latest,
            identity=lambda sub: f"submission {sub.id}",
        )
    except BatchExportFailed as exc:
        raise HTTPException(status_code=500, detail="全部 Word 文件匯出失敗，請檢查資料後重試") from exc

    safe_title = assignment.title.replace(" ", "_")[:40]
    download_name = f"{safe_title}_latest.zip"
    encoded_filename = quote(download_name)
    log_admin_action(
        db,
        admin,
        "admin.export.assignment_words_latest",
        request=request,
        target_type="assignment_export",
        target_id=assignment.id,
        target_label=download_name,
        summary=f"匯出作業最新 Word：{assignment.title}",
        details={
            "assignment_id": assignment.id,
            "attempted": result.attempted,
            "exported": result.exported,
            "failures": result.failures,
        },
    )
    db.commit()
    return StreamingResponse(
        io.BytesIO(result.archive),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-Export-Partial": "true" if result.partial else "false",
        },
    )


@router.get("/assignments/{assignment_id}/export-words")
def export_all_words(
    assignment_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    assignment = _get_accessible_assignment(db, admin, assignment_id)
    visible_students = _get_visible_students_for_assignment(db, admin, assignment)
    visible_student_ids = [student.id for student in visible_students]

    submissions = (
        db.query(Submission)
        .filter(
            Submission.assignment_id == assignment_id,
            Submission.submitted_at.isnot(None),
            Submission.user_id.in_(visible_student_ids) if visible_student_ids else False,
        )
        .all()
    ) if visible_student_ids else []

    sub_users_by_id = load_users_by_ids(db, (s.user_id for s in submissions))

    if not submissions:
        raise HTTPException(status_code=404, detail="沒有已完成的提交可匯出")
    safe_archive_title = assignment.title.translate(str.maketrans('', '', r'/\:*?"<>|'))[:40]

    def render_all(sub: Submission) -> tuple[str, bytes]:
        student = sub_users_by_id.get(sub.user_id)
        if student is None:
            raise ValueError("student row is missing")
        _hydrate_for_export(db, sub)
        filename = f"{safe_archive_title}_{student.student_id}_第{sub.attempt_number}次.docx"
        return filename, _build_submission_docx(student, assignment, sub)

    try:
        result = build_zip_with_manifest(
            submissions,
            render=render_all,
            identity=lambda sub: f"submission {sub.id}",
        )
    except BatchExportFailed as exc:
        raise HTTPException(status_code=500, detail="全部 Word 文件匯出失敗，請檢查資料後重試") from exc

    safe_title = assignment.title.replace(" ", "_")[:40]
    download_name = f"{safe_title}_words.zip"
    encoded_filename = quote(download_name)
    log_admin_action(
        db,
        admin,
        "admin.export.assignment_words_all",
        request=request,
        target_type="assignment_export",
        target_id=assignment.id,
        target_label=download_name,
        summary=f"匯出作業全部 Word：{assignment.title}",
        details={
            "assignment_id": assignment.id,
            "attempted": result.attempted,
            "exported": result.exported,
            "failures": result.failures,
        },
    )
    db.commit()
    return StreamingResponse(
        io.BytesIO(result.archive),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-Export-Partial": "true" if result.partial else "false",
        },
    )


# ── Assignment gradebook export ───────────────────────────────────────────────

@router.get("/assignments/{assignment_id}/export-xlsx")
def export_assignment_grades_xlsx(
    assignment_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    assignment = _get_accessible_assignment(db, admin, assignment_id)
    students = _get_visible_students_for_assignment(db, admin, assignment)
    student_ids = [student.id for student in students]
    submissions = (
        db.query(Submission)
        .filter(
            Submission.assignment_id == assignment_id,
            Submission.user_id.in_(student_ids),
        )
        .options(load_only(
            Submission.id,
            Submission.user_id,
            Submission.attempt_number,
            Submission.stage,
            Submission.submitted_at,
        ))
        .order_by(Submission.user_id, Submission.attempt_number.desc(), Submission.id.desc())
        .all()
    ) if student_ids else []

    latest_by_user = _latest_submissions_by_user(submissions)
    grades_by_submission = latest_grades_by_submission(
        db,
        [submission.id for submission in latest_by_user.values()],
    )
    workbook = _build_assignment_grade_workbook(
        assignment,
        students,
        submissions,
        grades_by_submission,
    )
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)

    filename = _safe_assignment_grade_filename(assignment)
    encoded_filename = quote(filename)
    log_admin_action(
        db,
        admin,
        "admin.export.assignment_xlsx",
        request=request,
        target_type="assignment_export",
        target_id=assignment.id,
        target_label=filename,
        summary=f"匯出作業成績 XLSX：{assignment.title}",
        details={
            "assignment_id": assignment.id,
            "student_count": len(students),
            "latest_attempt_count": len(latest_by_user),
            "graded_count": len(grades_by_submission),
        },
    )
    db.commit()
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="assignment_{assignment.id}_grades.xlsx"; '
                f"filename*=UTF-8''{encoded_filename}"
            ),
        },
    )
