"""Legal-document metadata and acknowledgement policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.services.admin_audit import log_actor_action
from app.utils import taipei_now


@dataclass(frozen=True)
class LegalDocument:
    title: str
    version: str
    url: str


PRIVACY_NOTICE = LegalDocument(
    title="個人資料蒐集、處理及利用告知事項",
    version="2026-07-22.2",
    url="https://docs.oral.brid.pw/legal/privacy-notice/",
)
SYSTEM_TERMS = LegalDocument(
    title="AI 英語面試練習系統使用者條款暨可接受使用規範",
    version="2026-07-22.2",
    url="https://docs.oral.brid.pw/legal/system-terms/",
)


def public_documents() -> dict[str, dict[str, str]]:
    return {
        "privacy_notice": asdict(PRIVACY_NOTICE),
        "system_terms": asdict(SYSTEM_TERMS),
    }


def requires_acknowledgement(user) -> bool:
    return user.role == "student" and (
        user.privacy_notice_version != PRIVACY_NOTICE.version
        or user.privacy_acknowledged_at is None
        or user.system_terms_version != SYSTEM_TERMS.version
        or user.system_terms_accepted_at is None
    )


def validate_acknowledgement(payload) -> None:
    if not payload.privacy_acknowledged:
        raise HTTPException(status_code=400, detail="請先閱讀並勾選個人資料告知事項")
    if not payload.terms_accepted:
        raise HTTPException(status_code=400, detail=f"請先閱讀並同意「{SYSTEM_TERMS.title}」")
    if (
        payload.privacy_notice_version != PRIVACY_NOTICE.version
        or payload.system_terms_version != SYSTEM_TERMS.version
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="法遵文件已有新版本，請重新載入並閱讀後再確認。",
        )


def record_acknowledgement(
    db: Session,
    request: Request,
    user,
    payload,
) -> None:
    validate_acknowledgement(payload)
    acknowledged_at = taipei_now()
    user.privacy_notice_version = PRIVACY_NOTICE.version
    user.privacy_acknowledged_at = acknowledged_at
    user.system_terms_version = SYSTEM_TERMS.version
    user.system_terms_accepted_at = acknowledged_at
    log_actor_action(
        db,
        "student.legal.acknowledge",
        actor_student_id=user.student_id,
        actor_name=user.name,
        actor_user=user,
        request=request,
        target_type="user",
        target_id=user.id,
        target_label=user.student_id,
        summary="確認現行個資告知事項與系統使用者條款",
        details={
            "privacy_notice_version": PRIVACY_NOTICE.version,
            "system_terms_version": SYSTEM_TERMS.version,
        },
    )
