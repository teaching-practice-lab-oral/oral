"""Single source of truth for the student workflow contract.

Keep workflow names, navigation and numeric limits here.  Routers, exports,
audit views and browser code consume :func:`workflow_metadata_payload` instead
of maintaining parallel stage tables.
"""

from dataclasses import asdict, dataclass

CORE_QUESTION_COUNT = 4
REFLECTION_QUESTION_COUNT = 5
SECRET_QUESTION_COUNT = 1
SECRET_QUESTION_SOURCE_INDEX = CORE_QUESTION_COUNT
MAX_ROLEPLAY_TURNS = CORE_QUESTION_COUNT * 2 + SECRET_QUESTION_COUNT
WORKFLOW_VERSION = 2
# Per-question cap keeps a full four-question response inside
# STAGE3_MAX_RESPONSE_CHARS; the prompt asks for the most important first.
MAX_GRAMMAR_CORRECTIONS = 8
REFLECTION_QUESTIONS = (
    "這次練習中，你最滿意或最有進步的地方是什麼？請舉一個具體例子。",
    "寫作、跟讀、角色扮演中，哪一部分最有挑戰？你遇到什麼困難，又如何處理？",
    "看完 AI 回饋後，你認為自己的一項優勢與一項最需要改進的地方是什麼？",
    "如果重新進行一次面試，你會如何調整準備方式或回答內容？",
    "請訂下一個具體行動：要做什麼、何時完成、如何確認自己有進步？",
)
assert len(REFLECTION_QUESTIONS) == REFLECTION_QUESTION_COUNT


@dataclass(frozen=True)
class WorkflowLimits:
    max_attempts: int
    max_feedback_count: int
    max_shadowing_attempts: int
    core_question_count: int
    reflection_question_count: int
    secret_question_source_index: int
    max_roleplay_turns: int


@dataclass(frozen=True)
class WorkflowSection:
    id: int
    key: str
    label: str
    path: str


@dataclass(frozen=True)
class WorkflowStage:
    number: int
    key: str
    label: str


WORKFLOW_LIMITS = WorkflowLimits(
    max_attempts=3,
    max_feedback_count=3,
    max_shadowing_attempts=2,
    core_question_count=CORE_QUESTION_COUNT,
    reflection_question_count=REFLECTION_QUESTION_COUNT,
    secret_question_source_index=SECRET_QUESTION_SOURCE_INDEX,
    max_roleplay_turns=MAX_ROLEPLAY_TURNS,
)

WORKFLOW_SECTIONS = (
    WorkflowSection(1, "job_profile", "欲應徵的職位", "job-profile"),
    WorkflowSection(2, "writing", "寫作練習", "writing"),
    WorkflowSection(3, "shadowing", "跟讀練習", "shadowing"),
    WorkflowSection(4, "roleplay", "角色扮演", "roleplay"),
    WorkflowSection(5, "report", "AI 回饋", "report"),
    WorkflowSection(6, "reflection", "心得撰寫", "reflection"),
)

WORKFLOW_STAGES = (
    WorkflowStage(1, "job_profile", "職位資料"),
    WorkflowStage(2, "draft", "草稿撰寫"),
    WorkflowStage(3, "writing_feedback", "AI 練習回饋"),
    WorkflowStage(4, "final_draft", "最終草稿"),
    WorkflowStage(5, "shadowing", "跟讀練習"),
    WorkflowStage(6, "roleplay", "角色扮演"),
    WorkflowStage(7, "secret_question", "臨場追問"),
    WorkflowStage(8, "report_and_reflection", "AI 回饋與心得撰寫"),
    WorkflowStage(9, "completed", "正式完成"),
)

_STAGE_LABELS = {stage.number: stage.label for stage in WORKFLOW_STAGES}


def workflow_limits_payload() -> dict[str, int]:
    return asdict(WORKFLOW_LIMITS)


def workflow_stage_label(stage: int | None) -> str | None:
    """Return the canonical display label for a persisted workflow stage."""
    if stage is None:
        return None
    return _STAGE_LABELS.get(int(stage))


def workflow_metadata_payload() -> dict:
    """Return the stable public workflow contract consumed by browser clients."""
    return {
        "version": WORKFLOW_VERSION,
        "sections": [asdict(section) for section in WORKFLOW_SECTIONS],
        "stages": [asdict(stage) for stage in WORKFLOW_STAGES],
        "limits": workflow_limits_payload(),
    }
