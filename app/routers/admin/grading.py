"""Formal grading and AI-feedback regeneration endpoints."""

import logging
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import get_current_admin
from app.database import get_db
from app.models import SubmissionGradeRevision, User
from app.rubrics import calculate_rubric_score
from app.schemas import GradeCreateRequest, GradeRevisionAdminResponse, SubmissionResponse
from app.services.admin_audit import log_admin_action, snapshot_submission
from app.services.admin_submission_access import get_accessible_submission_context
from app.services.grading import (
    grade_admin_payload,
    latest_grade,
    score_differs,
    submission_is_complete_for_grading,
)
from app.services.operation_lock import ROLEPLAY_REPORT_OPERATION, acquire_operation_lock
from app.services.report_generation import build_report_request, generate_report, save_report_if_current
from app.services.submission_data import build_roleplay_conversation, hydrate_submission_from_normalized


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin-grading"])


@router.get("/submissions/{submission_id}/grades", response_model=List[GradeRevisionAdminResponse])
def list_grade_history(
    submission_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    get_accessible_submission_context(db, admin, submission_id, hydrate=False)
    rows = db.query(SubmissionGradeRevision).filter(
        SubmissionGradeRevision.origin_submission_id == submission_id
    ).order_by(SubmissionGradeRevision.revision_number.desc()).all()
    return [GradeRevisionAdminResponse(**grade_admin_payload(row)) for row in rows]


@router.post("/submissions/{submission_id}/grades", response_model=GradeRevisionAdminResponse, status_code=201)
def save_grade(
    submission_id: int,
    payload: GradeCreateRequest,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    submission, student, assignment = get_accessible_submission_context(
        db, admin, submission_id, lock=True, hydrate=False
    )
    if not submission_is_complete_for_grading(submission):
        raise HTTPException(status_code=409, detail="學生尚未完成心得，無法批改")
    final_decimal = Decimal(str(payload.final_score))
    if final_decimal != final_decimal.quantize(Decimal("0.1")):
        raise HTTPException(status_code=400, detail="教師最後分最多只能有一位小數")
    version = submission.rubric_version
    if not version or version.status != "published":
        raise HTTPException(status_code=409, detail="這次作答沒有可用的已發布評分規準")
    rubric_score, ratings = calculate_rubric_score(version.definition, payload.ratings)
    previous = latest_grade(db, submission.id)
    reason = (payload.change_reason or "").strip() or None
    if (previous or score_differs(rubric_score, payload.final_score)) and not reason:
        raise HTTPException(status_code=400, detail="調整分數或異動既有成績時，必須填寫異動理由")
    row = SubmissionGradeRevision(
        origin_submission_id=submission.id,
        origin_assignment_id=assignment.id,
        origin_user_id=student.id,
        revision_number=(previous.revision_number + 1) if previous else 1,
        rubric_version_id=version.id,
        rubric_name=version.rubric.name,
        rubric_version_number=version.version_number,
        rubric_snapshot=version.definition,
        ratings_json=ratings,
        rubric_score=rubric_score,
        final_score=final_decimal,
        teacher_comment=payload.teacher_comment.strip(),
        teacher_feedback=payload.teacher_feedback.strip(),
        change_reason=reason,
        grader_user_id=admin.id,
        grader_student_id=admin.student_id,
        grader_name=admin.name,
        student_id_snapshot=student.student_id,
        student_name_snapshot=student.name,
        assignment_title_snapshot=assignment.title,
    )
    db.add(row)
    db.flush()
    log_admin_action(
        db, admin, "admin.submission.grade", request=request,
        target_type="submission_grade", target_id=row.id,
        target_label=f"assignment:{assignment.id}/submission:{submission.id}/student:{student.student_id}",
        before=grade_admin_payload(previous) if previous else None,
        after={
            "revision_number": row.revision_number,
            "rubric_score": float(row.rubric_score),
            "final_score": float(row.final_score),
            "rubric_version_id": version.id,
        },
        summary=f"儲存 {student.name} 成績：{float(row.final_score):g} 分（第 {row.revision_number} 版）",
        details={"change_reason": reason},
    )
    db.commit()
    db.refresh(row)
    return GradeRevisionAdminResponse(**grade_admin_payload(row))


@router.post("/submissions/{submission_id}/rescore", response_model=SubmissionResponse)
async def regenerate_submission_feedback(
    submission_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    admin_id = admin.id
    get_accessible_submission_context(db, admin, submission_id)
    db.rollback()
    lease = await acquire_operation_lock(submission_id, ROLEPLAY_REPORT_OPERATION)
    try:
        admin = db.query(User).filter(User.id == admin_id).first()
        if not admin:
            raise HTTPException(status_code=401, detail="Admin session expired")
        submission, _, _ = get_accessible_submission_context(db, admin, submission_id, lock=True)
        conversation = build_roleplay_conversation(db, submission)
        if not conversation.get("turns"):
            raise HTTPException(status_code=400, detail="沒有可重新產生 AI 回饋的角色扮演資料")
        report_request = build_report_request(db, submission, conversation["turns"])
        expected_hash = report_request.input_hash
        before = snapshot_submission(submission)
        db.rollback()
        report = await generate_report(report_request)
        admin = db.query(User).filter(User.id == admin_id).first()
        if not admin:
            raise HTTPException(status_code=401, detail="管理員登入已失效")
        submission, _, _ = get_accessible_submission_context(db, admin, submission_id, lock=True)
        if not save_report_if_current(db, submission, report, expected_hash):
            db.rollback()
            raise HTTPException(status_code=409, detail="學生作答內容已更新，請重新產生 AI 回饋")
        log_admin_action(
            db, admin, "admin.submission.rescore", request=request,
            target_type="submission", target_id=submission.id,
            target_label=f"assignment:{submission.assignment_id}/user:{submission.user_id}",
            before=before, after=snapshot_submission(submission),
            summary=f"重新產生 submission {submission.id} AI 回饋",
        )
        db.commit()
        db.refresh(submission)
        hydrate_submission_from_normalized(db, submission)
        logger.info("Admin %s regenerated feedback for submission %s", admin.student_id, submission_id)
        return SubmissionResponse.model_validate(submission)
    finally:
        await lease.release()
