"""Shared request composition and persistence for roleplay reports."""

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from app.models import Submission
from app.services import openai_chat
from app.services.prompt_composition import compose_stage_request
from app.services.submission_data import (
    get_job_profile_data,
    list_question_snapshot,
    replace_report,
    report_input_hash,
)
from app.services.roleplay_policy import build_relevance_block


ReportBullet = Annotated[str, Field(min_length=1, max_length=500)]


class _ReportAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language_complexity: list[ReportBullet] = Field(min_length=2, max_length=3)
    language_accuracy: list[ReportBullet] = Field(min_length=2, max_length=3)
    content_logic: list[ReportBullet] = Field(min_length=2, max_length=3)
    interview_strategy: list[ReportBullet] = Field(min_length=2, max_length=3)

    @field_validator("*", mode="after")
    @classmethod
    def _strip_bullets(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("report bullets cannot be blank")
        return stripped


class _QualitativeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: _ReportAnalysis
    strengths: list[ReportBullet] = Field(min_length=2, max_length=2)
    overall_suggestions: list[ReportBullet] = Field(min_length=3, max_length=3)

    @field_validator("strengths", "overall_suggestions", mode="after")
    @classmethod
    def _strip_bullets(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("report bullets cannot be blank")
        return stripped


def report_response_format() -> dict:
    bullet = {"type": "string", "minLength": 1, "maxLength": 500}
    analysis_properties = {
        name: {
            "type": "array",
            "items": bullet,
            "minItems": 2,
            "maxItems": 3,
        }
        for name in (
            "language_complexity",
            "language_accuracy",
            "content_logic",
            "interview_strategy",
        )
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "qualitative_roleplay_report",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "analysis": {
                        "type": "object",
                        "properties": analysis_properties,
                        "required": list(analysis_properties),
                        "additionalProperties": False,
                    },
                    "strengths": {
                        "type": "array", "items": bullet,
                        "minItems": 2, "maxItems": 2,
                    },
                    "overall_suggestions": {
                        "type": "array", "items": bullet,
                        "minItems": 3, "maxItems": 3,
                    },
                },
                "required": ["analysis", "strengths", "overall_suggestions"],
                "additionalProperties": False,
            },
        },
    }


@dataclass(frozen=True)
class ReportRequest:
    system_prompt: str
    user_message: str
    input_hash: str


def build_report_request(
    db: Session,
    submission: Submission,
    turns: list[dict],
    core_questions: list[str] | None = None,
) -> ReportRequest:
    questions = core_questions or list_question_snapshot(db, submission)
    conversation = [
        {
            "turn_number": turn.get("turn_number"),
            "source_question_index": turn.get("source_question_index"),
            "interviewer_question": turn.get("interviewer_question"),
            "candidate_transcript": turn.get("student_transcript") or "[no response]",
        }
        for turn in turns
    ]
    system_prompt, user_message = compose_stage_request(
        db,
        submission.assignment_id,
        8,
        label="candidate_report_evidence",
        payload={
            "conversation": conversation,
            "job_profile": get_job_profile_data(db, submission),
            "relevance_signals": build_relevance_block(turns, questions),
        },
    )
    return ReportRequest(
        system_prompt=system_prompt,
        user_message=user_message,
        input_hash=report_input_hash(db, submission),
    )


async def generate_report(request: ReportRequest) -> dict:
    raw = await openai_chat.chat_completion_json(
        request.system_prompt,
        request.user_message,
        temperature=0,
        response_format=report_response_format(),
    )
    try:
        return _QualitativeReport.model_validate(raw).model_dump()
    except ValidationError as exc:
        raise ValueError("AI 回傳的口語回饋格式不完整，已拒絕寫入") from exc


def save_report_if_current(
    db: Session,
    submission: Submission,
    report: dict,
    expected_hash: str,
) -> bool:
    if report_input_hash(db, submission) != expected_hash:
        return False
    replace_report(db, submission, report, input_hash=expected_hash)
    return True
