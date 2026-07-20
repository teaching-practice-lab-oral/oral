"""Prompt-template lifecycle rules shared by admin routes and assignment CRUD."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.models import PromptTemplate
from app.prompts import (
    DEFAULT_PROMPTS,
    STAGE6_ROLEPLAY_POLICY,
    STAGE6_SECRET_QUESTION_POLICY,
    SYSTEM_PROMPT_NAMES,
)


SUPPORTED_PROMPT_STAGES = frozenset(DEFAULT_PROMPTS)


class PromptTemplateValidationError(ValueError):
    """Raised when a prompt template violates a stage-specific invariant."""


def _required_text(value: str | None, label: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise PromptTemplateValidationError(f"{label}不可空白")
    return normalized


def _stage_policies(
    stage: int,
    roleplay_policy: str | None,
    secret_question_policy: str | None,
    *,
    use_stage6_defaults: bool,
) -> tuple[str | None, str | None]:
    if stage not in SUPPORTED_PROMPT_STAGES:
        raise PromptTemplateValidationError("stage 必須為 3、6 或 8")

    if stage != 6:
        if roleplay_policy is not None or secret_question_policy is not None:
            raise PromptTemplateValidationError("只有 Stage 6 可以設定角色扮演與秘密追問規則")
        return None, None

    if use_stage6_defaults:
        roleplay_policy = roleplay_policy or STAGE6_ROLEPLAY_POLICY
        secret_question_policy = secret_question_policy or STAGE6_SECRET_QUESTION_POLICY
    return (
        _required_text(roleplay_policy, "一般角色扮演規則"),
        _required_text(secret_question_policy, "秘密追問規則"),
    )


def ensure_system_templates(db: Session, admin_id: int | None = None) -> dict[int, int]:
    """Create/repair system templates without owning the surrounding transaction."""
    templates_by_stage = {
        row.stage: row
        for row in db.query(PromptTemplate).filter(PromptTemplate.is_system == True).all()
    }
    result: dict[int, int] = {}
    for stage, prompt_text in DEFAULT_PROMPTS.items():
        desired_name = SYSTEM_PROMPT_NAMES.get(stage, f"Stage {stage}")
        desired_roleplay, desired_secret = _stage_policies(
            stage,
            None,
            None,
            use_stage6_defaults=True,
        )
        template = templates_by_stage.get(stage)
        if template is None:
            template = PromptTemplate(
                stage=stage,
                name=desired_name,
                is_system=True,
                system_prompt=prompt_text,
                roleplay_policy=desired_roleplay,
                secret_question_policy=desired_secret,
                updated_by=admin_id,
            )
            db.add(template)
            templates_by_stage[stage] = template
        else:
            changed = False
            desired = {
                "name": desired_name,
                "system_prompt": prompt_text,
                "roleplay_policy": desired_roleplay,
                "secret_question_policy": desired_secret,
            }
            for field, value in desired.items():
                if getattr(template, field) != value:
                    setattr(template, field, value)
                    changed = True
            if changed:
                template.updated_by = admin_id

    db.flush()
    for stage in SUPPORTED_PROMPT_STAGES:
        result[stage] = templates_by_stage[stage].id
    return result


def sync_system_templates_from_code(db: Session, admin_id: int) -> dict[str, list[int]]:
    """Reset system templates to the versioned defaults, leaving commit to the route."""
    templates_by_stage = {
        row.stage: row
        for row in db.query(PromptTemplate).filter(PromptTemplate.is_system == True).all()
    }
    result: dict[str, list[int]] = {"created": [], "updated": [], "unchanged": []}
    for stage, prompt_text in DEFAULT_PROMPTS.items():
        label = SYSTEM_PROMPT_NAMES.get(stage, f"Stage {stage}")
        roleplay_policy, secret_question_policy = _stage_policies(
            stage,
            None,
            None,
            use_stage6_defaults=True,
        )
        template = templates_by_stage.get(stage)
        if template is None:
            db.add(PromptTemplate(
                stage=stage,
                name=label,
                is_system=True,
                system_prompt=prompt_text,
                roleplay_policy=roleplay_policy,
                secret_question_policy=secret_question_policy,
                updated_by=admin_id,
            ))
            result["created"].append(stage)
            continue

        changed = False
        desired = {
            "name": label,
            "system_prompt": prompt_text,
            "roleplay_policy": roleplay_policy,
            "secret_question_policy": secret_question_policy,
        }
        for field, value in desired.items():
            if getattr(template, field) != value:
                setattr(template, field, value)
                changed = True
        if changed:
            template.updated_by = admin_id
            result["updated"].append(stage)
        else:
            result["unchanged"].append(stage)
    return result


def validate_global_template_selection(
    db: Session,
    template_id: int | None,
    stage: int,
) -> int | None:
    """Return a valid global template id for the requested stage."""
    if template_id is None:
        return None
    template = db.query(PromptTemplate).filter(
        PromptTemplate.id == template_id,
        PromptTemplate.stage == stage,
    ).first()
    if template is None:
        raise PromptTemplateValidationError(f"Stage {stage} 必須選擇對應階段的全域提示詞模板")
    return template.id


def create_global_template(
    db: Session,
    *,
    stage: int,
    name: str,
    system_prompt: str,
    roleplay_policy: str | None,
    secret_question_policy: str | None,
    updated_by: int,
) -> PromptTemplate:
    roleplay_policy, secret_question_policy = _stage_policies(
        stage,
        roleplay_policy,
        secret_question_policy,
        use_stage6_defaults=True,
    )
    template = PromptTemplate(
        stage=stage,
        name=_required_text(name, "名稱"),
        is_system=False,
        system_prompt=_required_text(system_prompt, "提示詞內容"),
        roleplay_policy=roleplay_policy,
        secret_question_policy=secret_question_policy,
        updated_by=updated_by,
    )
    db.add(template)
    return template


def apply_global_template_update(
    template: PromptTemplate,
    changes: Mapping[str, Any],
    *,
    updated_by: int,
) -> None:
    new_name = template.name
    new_system_prompt = template.system_prompt
    if "name" in changes and changes["name"] is not None and not template.is_system:
        new_name = _required_text(changes["name"], "名稱")
    if "system_prompt" in changes and changes["system_prompt"] is not None:
        new_system_prompt = _required_text(changes["system_prompt"], "提示詞內容")

    policy_fields_supplied = any(
        field in changes for field in ("roleplay_policy", "secret_question_policy")
    )
    if template.stage == 6:
        if policy_fields_supplied:
            new_roleplay_policy = changes.get("roleplay_policy", template.roleplay_policy)
            new_secret_question_policy = changes.get(
                "secret_question_policy",
                template.secret_question_policy,
            )
            new_roleplay_policy, new_secret_question_policy = _stage_policies(
                6,
                new_roleplay_policy,
                new_secret_question_policy,
                use_stage6_defaults=False,
            )
        else:
            new_roleplay_policy, new_secret_question_policy = _stage_policies(
                6,
                template.roleplay_policy,
                template.secret_question_policy,
                use_stage6_defaults=True,
            )
    elif policy_fields_supplied and any(
        changes.get(field) is not None
        for field in ("roleplay_policy", "secret_question_policy")
    ):
        raise PromptTemplateValidationError("只有 Stage 6 可以設定角色扮演與秘密追問規則")
    else:
        new_roleplay_policy = None
        new_secret_question_policy = None

    template.name = new_name
    template.system_prompt = new_system_prompt
    template.roleplay_policy = new_roleplay_policy
    template.secret_question_policy = new_secret_question_policy
    template.updated_by = updated_by


def duplicate_global_template(
    db: Session,
    source: PromptTemplate,
    *,
    updated_by: int,
) -> PromptTemplate:
    roleplay_policy, secret_question_policy = _stage_policies(
        source.stage,
        source.roleplay_policy,
        source.secret_question_policy,
        use_stage6_defaults=True,
    )
    base_name = source.name or SYSTEM_PROMPT_NAMES.get(source.stage, f"Stage {source.stage}")
    template = PromptTemplate(
        stage=source.stage,
        name=f"{base_name}（複製）",
        is_system=False,
        system_prompt=_required_text(source.system_prompt, "提示詞內容"),
        roleplay_policy=roleplay_policy,
        secret_question_policy=secret_question_policy,
        updated_by=updated_by,
    )
    db.add(template)
    return template
