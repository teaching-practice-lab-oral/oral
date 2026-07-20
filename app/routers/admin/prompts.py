import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import get_current_admin
from app.database import get_db
from app.models import User, PromptTemplate
from app.schemas import (
    GlobalPromptTemplateCreate, GlobalPromptTemplateUpdate, GlobalPromptTemplateResponse,
)
from app.prompts import SYSTEM_PROMPT_NAMES
from app.services.admin_audit import log_admin_action, snapshot_prompt
from app.services.admin_scope import ensure_privileged_admin
from app.services.prompt_templates import (
    PromptTemplateValidationError,
    apply_global_template_update,
    create_global_template,
    duplicate_global_template,
    sync_system_templates_from_code,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _tmpl_to_response(t: PromptTemplate) -> GlobalPromptTemplateResponse:
    label = SYSTEM_PROMPT_NAMES.get(t.stage, f"Stage {t.stage}")
    return GlobalPromptTemplateResponse(
        id=t.id,
        name=t.name or label,
        stage=t.stage,
        stage_label=label,
        system_prompt=t.system_prompt,
        is_system=t.is_system,
        updated_at=t.updated_at,
        roleplay_policy=t.roleplay_policy,
        secret_question_policy=t.secret_question_policy,
    )


@router.post("/prompts/sync-defaults")
def sync_prompt_defaults(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Overwrite DB system-default prompts with the code defaults in app/prompts.py."""
    ensure_privileged_admin(admin, "只有指定管理員可同步系統預設提示詞")
    before_rows = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.is_system == True)
        .all()
    )
    before = {row.stage: snapshot_prompt(row) for row in before_rows}
    result = sync_system_templates_from_code(db, admin.id)
    db.flush()
    after_rows = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.is_system == True)
        .all()
    )
    after = {row.stage: snapshot_prompt(row) for row in after_rows}
    log_admin_action(
        db,
        admin,
        "admin.prompt.sync_defaults",
        request=request,
        target_type="prompt_template_batch",
        target_label="system-default-prompts",
        before=before,
        after=after,
        summary=(
            f"同步系統預設提示詞：新增 {len(result['created'])} 筆、"
            f"更新 {len(result['updated'])} 筆、未變更 {len(result['unchanged'])} 筆"
        ),
        details=result,
    )
    db.commit()
    return result


# ── Global Named Prompt Templates ─────────────────────────────────────────────

@router.get("/prompts", response_model=List[GlobalPromptTemplateResponse])
def list_global_prompts(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """List all named prompt templates, grouped by workflow stage."""
    ensure_privileged_admin(admin, "只有指定管理員可檢視全域提示詞")
    templates = (
        db.query(PromptTemplate)
        .order_by(PromptTemplate.stage, PromptTemplate.is_system.desc(), PromptTemplate.updated_at)
        .all()
    )
    return [_tmpl_to_response(t) for t in templates]


@router.post("/prompts", response_model=GlobalPromptTemplateResponse, status_code=201)
def create_global_prompt(
    payload: GlobalPromptTemplateCreate,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ensure_privileged_admin(admin, "只有指定管理員可管理全域提示詞")
    try:
        t = create_global_template(
            db,
            stage=payload.stage,
            name=payload.name,
            system_prompt=payload.system_prompt,
            roleplay_policy=payload.roleplay_policy,
            secret_question_policy=payload.secret_question_policy,
            updated_by=admin.id,
        )
    except PromptTemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.flush()
    log_admin_action(
        db,
        admin,
        "admin.prompt.create",
        request=request,
        target_type="prompt_template",
        target_id=t.id,
        target_label=t.name or SYSTEM_PROMPT_NAMES.get(t.stage, f"Stage {t.stage}"),
        after=snapshot_prompt(t),
        summary=f"建立全域提示詞：{t.name or t.id}",
    )
    db.commit()
    db.refresh(t)
    logger.info("Admin %s created global prompt template id=%s stage=%s", admin.student_id, t.id, t.stage)
    return _tmpl_to_response(t)


@router.put("/prompts/{template_id}", response_model=GlobalPromptTemplateResponse)
def update_global_prompt(
    template_id: int,
    payload: GlobalPromptTemplateUpdate,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ensure_privileged_admin(admin, "只有指定管理員可管理全域提示詞")
    t = db.query(PromptTemplate).filter(
        PromptTemplate.id == template_id,
    ).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    before = snapshot_prompt(t)
    try:
        apply_global_template_update(
            t,
            payload.model_dump(exclude_unset=True),
            updated_by=admin.id,
        )
    except PromptTemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_admin_action(
        db,
        admin,
        "admin.prompt.update",
        request=request,
        target_type="prompt_template",
        target_id=t.id,
        target_label=t.name or SYSTEM_PROMPT_NAMES.get(t.stage, f"Stage {t.stage}"),
        before=before,
        after=snapshot_prompt(t),
        summary=f"更新全域提示詞：{t.name or t.id}",
    )
    db.commit()
    db.refresh(t)
    return _tmpl_to_response(t)


@router.delete("/prompts/{template_id}", status_code=204)
def delete_global_prompt(
    template_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ensure_privileged_admin(admin, "只有指定管理員可管理全域提示詞")
    t = db.query(PromptTemplate).filter(
        PromptTemplate.id == template_id,
    ).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    if t.is_system:
        raise HTTPException(status_code=403, detail="系統預設提示詞不可刪除")
    before = snapshot_prompt(t)
    log_admin_action(
        db,
        admin,
        "admin.prompt.delete",
        request=request,
        target_type="prompt_template",
        target_id=t.id,
        target_label=t.name or SYSTEM_PROMPT_NAMES.get(t.stage, f"Stage {t.stage}"),
        before=before,
        summary=f"刪除全域提示詞：{t.name or t.id}",
    )
    db.delete(t)
    db.commit()


@router.post("/prompts/{template_id}/duplicate", response_model=GlobalPromptTemplateResponse, status_code=201)
def duplicate_global_prompt(
    template_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Duplicate a template (typically a system default) as a new editable custom template."""
    ensure_privileged_admin(admin, "只有指定管理員可管理全域提示詞")
    src = db.query(PromptTemplate).filter(
        PromptTemplate.id == template_id,
    ).first()
    if not src:
        raise HTTPException(status_code=404, detail="Template not found")
    base_name = src.name or SYSTEM_PROMPT_NAMES.get(src.stage, f"Stage {src.stage}")
    try:
        t = duplicate_global_template(db, src, updated_by=admin.id)
    except PromptTemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.flush()
    log_admin_action(
        db,
        admin,
        "admin.prompt.duplicate",
        request=request,
        target_type="prompt_template",
        target_id=t.id,
        target_label=t.name or SYSTEM_PROMPT_NAMES.get(t.stage, f"Stage {t.stage}"),
        details={"source_template_id": src.id},
        after=snapshot_prompt(t),
        summary=f"複製全域提示詞：{base_name}",
    )
    db.commit()
    db.refresh(t)
    return _tmpl_to_response(t)
