from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_admin
from app.database import get_db
from app.models import (
    Assignment,
    Rubric,
    RubricVersion,
    Submission,
    SubmissionGradeRevision,
    User,
)
from app.rubrics import validate_rubric_definition
from app.schemas import (
    RubricCreateRequest,
    RubricVersionResponse,
    RubricVersionUpdateRequest,
)
from app.services.admin_audit import log_admin_action
from app.services.admin_scope import ensure_privileged_admin
from app.services.admin_submission_access import get_accessible_submission_context
from app.services.grading import rubric_version_payload
from app.utils import taipei_now


router = APIRouter(prefix="/api/admin", tags=["admin-rubrics"])


def _version_or_404(db: Session, version_id: int) -> RubricVersion:
    version = db.query(RubricVersion).filter(RubricVersion.id == version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="找不到這個評分規準版本")
    return version


def _ensure_rubric_not_archived(version: RubricVersion, action: str) -> None:
    if version.rubric.is_archived:
        raise HTTPException(status_code=409, detail=f"已封存的評分規準不可{action}")


@router.get("/rubrics", response_model=List[RubricVersionResponse])
def list_rubrics(
    include_drafts: bool = False,
    include_version_id: int | None = None,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(RubricVersion).join(Rubric, Rubric.id == RubricVersion.rubric_id)
    if not include_drafts or not admin.is_privileged_admin:
        archived_filter = Rubric.is_archived == False
        if include_version_id is not None:
            archived_filter = or_(archived_filter, RubricVersion.id == include_version_id)
        query = query.filter(RubricVersion.status == "published", archived_filter)
    versions = query.order_by(Rubric.name, RubricVersion.version_number.desc()).all()
    return [RubricVersionResponse(**rubric_version_payload(version)) for version in versions]


@router.post("/rubrics", response_model=RubricVersionResponse, status_code=201)
def create_rubric(
    payload: RubricCreateRequest,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ensure_privileged_admin(admin, "只有最高權限管理員可以建立評分規準")
    definition = validate_rubric_definition(payload.definition.model_dump(exclude_none=True))
    rubric = Rubric(
        name=payload.name.strip(),
        description=(payload.description or "").strip() or None,
        created_by=admin.id,
    )
    db.add(rubric)
    db.flush()
    version = RubricVersion(
        rubric_id=rubric.id,
        version_number=1,
        status="draft",
        definition=definition,
        created_by=admin.id,
    )
    db.add(version)
    db.flush()
    log_admin_action(
        db, admin, "admin.rubric.create", request=request,
        target_type="rubric", target_id=rubric.id, target_label=rubric.name,
        after={"version_id": version.id, "version_number": 1},
        summary=f"建立評分規準草稿：{rubric.name} v1",
    )
    db.commit()
    db.refresh(version)
    return RubricVersionResponse(**rubric_version_payload(version))


@router.put("/rubric-versions/{version_id}", response_model=RubricVersionResponse)
def update_rubric_version(
    version_id: int,
    payload: RubricVersionUpdateRequest,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ensure_privileged_admin(admin, "只有最高權限管理員可以修改評分規準")
    version = _version_or_404(db, version_id)
    _ensure_rubric_not_archived(version, "修改")
    if version.status != "draft":
        raise HTTPException(status_code=409, detail="已發布的評分規準不能直接修改，請先建立新版本")
    before = rubric_version_payload(version)
    has_published_version = db.query(RubricVersion.id).filter(
        RubricVersion.rubric_id == version.rubric_id,
        RubricVersion.status == "published",
    ).first() is not None
    requested_name = payload.name if payload.name is not None else version.rubric.name
    requested_description = (
        payload.description.strip() or None
        if payload.description is not None
        else version.rubric.description
    )
    if has_published_version and (
        requested_name != version.rubric.name
        or requested_description != version.rubric.description
    ):
        raise HTTPException(
            status_code=409,
            detail="已有發布版本後，名稱與說明不可再修改；請只調整新版的評分內容",
        )
    validated_definition = validate_rubric_definition(payload.definition.model_dump(exclude_none=True))
    if not has_published_version:
        version.rubric.name = requested_name
        version.rubric.description = requested_description
    version.definition = validated_definition
    log_admin_action(
        db, admin, "admin.rubric.update", request=request,
        target_type="rubric_version", target_id=version.id,
        target_label=f"{version.rubric.name} v{version.version_number}",
        before=before, after=rubric_version_payload(version),
        summary=f"更新評分規準草稿：{version.rubric.name} v{version.version_number}",
    )
    db.commit()
    db.refresh(version)
    return RubricVersionResponse(**rubric_version_payload(version))


@router.post("/rubric-versions/{version_id}/publish", response_model=RubricVersionResponse)
def publish_rubric_version(
    version_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ensure_privileged_admin(admin, "只有最高權限管理員可以發布評分規準")
    version = _version_or_404(db, version_id)
    _ensure_rubric_not_archived(version, "發布")
    if version.status == "published":
        return RubricVersionResponse(**rubric_version_payload(version))
    version.definition = validate_rubric_definition(version.definition)
    version.status = "published"
    version.published_at = taipei_now()
    log_admin_action(
        db, admin, "admin.rubric.publish", request=request,
        target_type="rubric_version", target_id=version.id,
        target_label=f"{version.rubric.name} v{version.version_number}",
        summary=f"發布評分規準：{version.rubric.name} v{version.version_number}",
    )
    db.commit()
    db.refresh(version)
    return RubricVersionResponse(**rubric_version_payload(version))


@router.post("/rubric-versions/{version_id}/new-version", response_model=RubricVersionResponse, status_code=201)
def clone_rubric_version(
    version_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ensure_privileged_admin(admin, "只有最高權限管理員可以建立評分規準的新版本")
    source = _version_or_404(db, version_id)
    _ensure_rubric_not_archived(source, "建立新版")
    max_version = max((version.version_number for version in source.rubric.versions), default=0)
    version = RubricVersion(
        rubric_id=source.rubric_id,
        version_number=max_version + 1,
        status="draft",
        definition=validate_rubric_definition(source.definition),
        created_by=admin.id,
    )
    db.add(version)
    db.flush()
    log_admin_action(
        db, admin, "admin.rubric.clone_version", request=request,
        target_type="rubric_version", target_id=version.id,
        target_label=f"{source.rubric.name} v{version.version_number}",
        summary=f"建立評分規準新版本草稿：{source.rubric.name} v{version.version_number}",
        details={"source_version_id": source.id},
    )
    db.commit()
    db.refresh(version)
    return RubricVersionResponse(**rubric_version_payload(version))


@router.delete("/rubric-versions/{version_id}", status_code=204)
def delete_rubric_draft_version(
    version_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ensure_privileged_admin(admin, "只有最高權限管理員可以刪除評分規準草稿")
    version = _version_or_404(db, version_id)
    _ensure_rubric_not_archived(version, "刪除草稿版本")
    if version.status != "draft":
        raise HTTPException(status_code=409, detail="只能刪除尚未發布的評分規準草稿")

    references = {
        "作業": db.query(Assignment.id).filter(Assignment.rubric_version_id == version.id).count(),
        "學生作答": db.query(Submission.id).filter(Submission.rubric_version_id == version.id).count(),
        "評分紀錄": db.query(SubmissionGradeRevision.id).filter(
            SubmissionGradeRevision.rubric_version_id == version.id
        ).count(),
    }
    referenced_by = [label for label, count in references.items() if count]
    if referenced_by:
        raise HTTPException(
            status_code=409,
            detail=f"這份草稿仍被{'、'.join(referenced_by)}引用，無法刪除",
        )

    rubric = version.rubric
    label = f"{rubric.name} v{version.version_number}"
    before = rubric_version_payload(version)
    version_count = db.query(RubricVersion.id).filter(
        RubricVersion.rubric_id == rubric.id
    ).count()
    db.delete(version)
    if version_count == 1 and not rubric.is_system:
        db.delete(rubric)
    log_admin_action(
        db, admin, "admin.rubric.delete_draft_version", request=request,
        target_type="rubric_version", target_id=version.id, target_label=label,
        before=before,
        summary=f"刪除評分規準草稿：{label}",
        details={"deleted_empty_rubric": version_count == 1 and not rubric.is_system},
    )
    db.commit()


@router.post("/rubrics/{rubric_id}/archive", status_code=204)
def archive_rubric(
    rubric_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ensure_privileged_admin(admin, "只有最高權限管理員可以封存評分規準")
    rubric = db.query(Rubric).filter(Rubric.id == rubric_id).first()
    if not rubric:
        raise HTTPException(status_code=404, detail="找不到這份評分規準")
    if rubric.is_system:
        raise HTTPException(status_code=409, detail="系統預設的評分規準不能封存")
    rubric.is_archived = True
    log_admin_action(
        db, admin, "admin.rubric.archive", request=request,
        target_type="rubric", target_id=rubric.id, target_label=rubric.name,
        summary=f"封存評分規準：{rubric.name}",
    )
    db.commit()


@router.get("/submissions/{submission_id}/rubric", response_model=RubricVersionResponse)
def get_submission_rubric(
    submission_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    submission, _, _ = get_accessible_submission_context(db, admin, submission_id, hydrate=False)
    return RubricVersionResponse(**rubric_version_payload(submission.rubric_version))
