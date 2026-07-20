"""Resolve and compose the exact prompts sent to AI services."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.models import Assignment, PromptTemplate
from app.prompts import (
    DEFAULT_PROMPTS,
    STAGE6_ROLEPLAY_POLICY,
    STAGE6_SECRET_QUESTION_POLICY,
)
from app.services.prompt_templates import SUPPORTED_PROMPT_STAGES


RoleplayPolicyKind = Literal["core", "secret"]


@dataclass(frozen=True)
class EffectivePrompt:
    stage: int
    template_id: int | None
    context: str
    system_prompt: str
    roleplay_policy: str | None = None
    secret_question_policy: str | None = None


def _assignment_template_id(assignment: Assignment, stage: int) -> int | None:
    return {
        3: assignment.stage3_template_id,
        6: assignment.stage6_template_id,
        8: assignment.stage8_template_id,
    }[stage]


def load_effective_prompt(db: Session, assignment_id: int, stage: int) -> EffectivePrompt:
    """Load one coherent template row and its assignment context without process cache."""
    if stage not in SUPPORTED_PROMPT_STAGES:
        raise ValueError(f"Unsupported prompt stage: {stage}")

    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    context = (assignment.prompt_context or "").strip() if assignment else ""
    template = None
    if assignment is not None:
        template_id = _assignment_template_id(assignment, stage)
        if template_id is not None:
            template = db.query(PromptTemplate).filter(
                PromptTemplate.id == template_id,
                PromptTemplate.stage == stage,
            ).first()
    if template is None:
        template = db.query(PromptTemplate).filter(
            PromptTemplate.is_system == True,
            PromptTemplate.stage == stage,
        ).first()

    system_prompt = (
        (template.system_prompt or "").strip()
        if template is not None
        else ""
    ) or DEFAULT_PROMPTS[stage]
    roleplay_policy = None
    secret_question_policy = None
    if stage == 6:
        roleplay_policy = (
            (template.roleplay_policy or "").strip()
            if template is not None
            else ""
        ) or STAGE6_ROLEPLAY_POLICY.strip()
        secret_question_policy = (
            (template.secret_question_policy or "").strip()
            if template is not None
            else ""
        ) or STAGE6_SECRET_QUESTION_POLICY.strip()

    return EffectivePrompt(
        stage=stage,
        template_id=template.id if template is not None else None,
        context=context,
        system_prompt=system_prompt,
        roleplay_policy=roleplay_policy,
        secret_question_policy=secret_question_policy,
    )


def _inject_context(template: str, context: str) -> str:
    if context and "{context}" in template:
        return template.replace("{context}", context)
    return "\n".join(line for line in template.splitlines() if "{context}" not in line)


def _inject_questions(template: str, questions: list[str] | None) -> str:
    if not questions:
        return "\n".join(line for line in template.splitlines() if "{questions}" not in line)
    formatted = "\n".join(f"{index + 1}. {question}" for index, question in enumerate(questions))
    return template.replace("{questions}", formatted)


def compose_stage_prompt(db: Session, assignment_id: int, stage: int) -> str:
    """Compose a Stage 3/6/8 base prompt with assignment context."""
    effective = load_effective_prompt(db, assignment_id, stage)
    return _inject_context(effective.system_prompt, effective.context)


def compose_roleplay_system_prompt(
    db: Session,
    assignment_id: int,
    core_questions: list[str],
    policy_kind: RoleplayPolicyKind,
) -> str:
    """Compose Stage 6 from a single effective row so prompt and policy cannot diverge."""
    effective = load_effective_prompt(db, assignment_id, 6)
    base = _inject_questions(
        _inject_context(effective.system_prompt, effective.context),
        core_questions,
    )
    if policy_kind == "core":
        policy = effective.roleplay_policy
    elif policy_kind == "secret":
        policy = effective.secret_question_policy
    else:
        raise ValueError(f"Unsupported roleplay policy kind: {policy_kind}")
    if policy is None:
        raise ValueError(f"Missing Stage 6 {policy_kind} policy")
    return f"{base.rstrip()}\n\n{policy.strip()}"
