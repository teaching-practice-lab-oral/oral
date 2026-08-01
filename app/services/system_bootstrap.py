"""Idempotent creation and repair of required system-owned data."""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy.orm import Session

from app.models import Rubric, RubricVersion
from app.rubrics import DEFAULT_RUBRIC_DEFINITION
from app.utils import taipei_now


SYSTEM_RUBRIC_NAME = "AI 英語面試練習評分規準"
SYSTEM_RUBRIC_DESCRIPTION = "整合回答內容、組織策略、語言運用、口語表達、互動應對與回饋反思的分析式評量尺規。"


def ensure_system_rubric(db: Session, actor_id: int | None = None) -> RubricVersion:
    rubrics = db.query(Rubric).filter(Rubric.is_system == True).order_by(Rubric.id).all()
    rubric = rubrics[0] if rubrics else None
    if rubric is None:
        rubric = Rubric(
            name=SYSTEM_RUBRIC_NAME,
            description=SYSTEM_RUBRIC_DESCRIPTION,
            is_system=True,
            created_by=actor_id,
        )
        db.add(rubric)
        db.flush()
    rubric.name = SYSTEM_RUBRIC_NAME
    rubric.description = SYSTEM_RUBRIC_DESCRIPTION
    rubric.is_archived = False

    # A clean baseline should only have one system rubric.  If older manual
    # bootstrap attempts left extras, archive them rather than deleting rows
    # that may already be referenced.
    for duplicate in rubrics[1:]:
        duplicate.is_system = False
        duplicate.is_archived = True

    published_versions = db.query(RubricVersion).filter(
        RubricVersion.rubric_id == rubric.id,
        RubricVersion.status == "published",
    ).order_by(RubricVersion.version_number.desc()).all()
    version = published_versions[0] if published_versions else None
    if version is None:
        max_number = max((row.version_number for row in rubric.versions), default=0)
        version = RubricVersion(
            rubric_id=rubric.id,
            version_number=max_number + 1,
            status="published",
            definition=deepcopy(DEFAULT_RUBRIC_DEFINITION),
            created_by=actor_id,
            published_at=taipei_now(),
        )
        db.add(version)
        db.flush()
    elif version.definition != DEFAULT_RUBRIC_DEFINITION:
        # Bootstrap is the code-owned repair path.  A published system default
        # is not teacher-editable, so keeping it aligned does not rewrite a
        # custom rubric or a historical grade snapshot.
        version.definition = deepcopy(DEFAULT_RUBRIC_DEFINITION)
    for obsolete in published_versions[1:]:
        obsolete.status = "draft"
        obsolete.published_at = None
    return version


def bootstrap_system_data(db: Session, actor_id: int | None = None) -> dict:
    rubric_version = ensure_system_rubric(db, actor_id)
    return {
        "rubric_version_id": rubric_version.id,
    }
