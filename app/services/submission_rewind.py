"""Admin rewind: send one in-progress attempt back to an earlier stage.

Rewinding to stage N clears everything the student produced in stage N and
after, so the student restarts that stage with a clean slate while earlier
work is kept.  Objects (recordings, TTS, photos) are queued for deletion in
the same transaction.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import (
    RoleplayTurn,
    ShadowingRecord,
    Submission,
    SubmissionAnswer,
    SubmissionJobProfile,
    SubmissionReflection,
    SubmissionReport,
)
from app.services import storage
from app.services.submission_assets import enqueue_object_cleanup
from app.services.workflow_policy import workflow_stage_label

# Stages an admin can restart from.  7 (mid-roleplay) and 9 (completed) are
# not starting points of their own.
REWINDABLE_STAGES = (1, 2, 3, 4, 5, 6, 8)


@dataclass(frozen=True)
class RewindResult:
    from_stage: int
    to_stage: int
    cleared: list[str]
    queued_objects: int


def rewind_submission(db: Session, sub: Submission, target_stage: int) -> RewindResult:
    """Clear stage ``target_stage`` and later content, then set the stage.

    The caller must hold a row lock on ``sub`` and has already checked access.
    """
    if target_stage not in REWINDABLE_STAGES:
        raise ValueError("unsupported target stage")
    from_stage = int(sub.stage or 1)
    if target_stage > from_stage:
        raise ValueError("cannot rewind forward")

    cleared: list[str] = []
    object_keys: list[str] = []

    # Stage 8: reflection (and the final submission).
    reflection = (
        db.query(SubmissionReflection)
        .filter(SubmissionReflection.submission_id == sub.id)
        .first()
    )
    if reflection is not None:
        if reflection.photo_key:
            object_keys.append(reflection.photo_key)
        db.delete(reflection)
        cleared.append("心得")
    sub.submitted_at = None

    if target_stage <= 6:
        report = db.query(SubmissionReport).filter(SubmissionReport.submission_id == sub.id).first()
        if report is not None:
            db.delete(report)
            cleared.append("AI 回饋報告")
        turns = db.query(RoleplayTurn).filter(RoleplayTurn.submission_id == sub.id).all()
        for turn in turns:
            object_keys.extend(k for k in (turn.interviewer_tts_key, turn.student_audio_key) if k)
            db.delete(turn)
        if turns:
            cleared.append("角色扮演")
        sub.practice_completed_at = None

    if target_stage <= 5:
        records = db.query(ShadowingRecord).filter(ShadowingRecord.submission_id == sub.id).all()
        had_recordings = False
        for record in records:
            if record.audio_key or record.transcript:
                had_recordings = True
            if record.audio_key:
                object_keys.append(record.audio_key)
            if target_stage == 5 and record.tts_key:
                # Model audio still matches the final draft: keep it and
                # only reset the student's own recording.
                record.audio_key = None
                record.transcript = None
                record.metrics = None
                record.attempts = 0
            else:
                if record.tts_key:
                    object_keys.append(record.tts_key)
                db.delete(record)
        if had_recordings:
            cleared.append("跟讀錄音")

    if target_stage <= 4:
        deleted = (
            db.query(SubmissionAnswer)
            .filter(SubmissionAnswer.submission_id == sub.id, SubmissionAnswer.answer_type == "final")
            .delete(synchronize_session=False)
        )
        if deleted:
            cleared.append("最終草稿")

    if target_stage <= 3:
        if sub.draft2_ai_feedback is not None or (sub.feedback_count or 0) > 0:
            cleared.append("AI 練習回饋")
        sub.draft2_ai_feedback = None
        sub.feedback_count = 0

    if target_stage <= 2:
        deleted = (
            db.query(SubmissionAnswer)
            .filter(SubmissionAnswer.submission_id == sub.id, SubmissionAnswer.answer_type == "draft1")
            .delete(synchronize_session=False)
        )
        if deleted:
            cleared.append("草稿")

    if target_stage <= 1:
        profile = db.query(SubmissionJobProfile).filter(SubmissionJobProfile.submission_id == sub.id).first()
        if profile is not None:
            db.delete(profile)
            cleared.append("職位資料與學習鷹架")

    sub.stage = target_stage
    owned_keys = [key for key in object_keys if storage.is_current_owned_key(key)]
    queued = enqueue_object_cleanup(db, owned_keys)
    cleared.reverse()
    return RewindResult(
        from_stage=from_stage,
        to_stage=target_stage,
        cleared=cleared,
        queued_objects=queued,
    )


def rewind_summary(result: RewindResult) -> str:
    label = workflow_stage_label(result.to_stage) or f"第 {result.to_stage} 階段"
    if result.cleared:
        return f"退回「{label}」，已清除：{'、'.join(result.cleared)}"
    return f"退回「{label}」"
