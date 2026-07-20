"""Shared request composition and persistence for roleplay reports."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Submission
from app.services import openai_chat
from app.services.prompt_composition import compose_stage_prompt
from app.services.submission_data import (
    job_profile_context,
    list_question_snapshot,
    replace_report,
    report_input_hash,
)
from app.services.roleplay_policy import build_relevance_block


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
    transcript = "\n".join(
        f"Interviewer: {turn['interviewer_question']}\n"
        f"Candidate: {turn.get('student_transcript') or '[no response]'}"
        for turn in turns
    )
    transcript += build_relevance_block(turns, questions)
    transcript += job_profile_context(db, submission)
    return ReportRequest(
        system_prompt=compose_stage_prompt(db, submission.assignment_id, 8),
        user_message=transcript,
        input_hash=report_input_hash(db, submission),
    )


async def generate_report(request: ReportRequest) -> dict:
    return await openai_chat.chat_completion_json(
        request.system_prompt,
        request.user_message,
        temperature=0,
    )


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
