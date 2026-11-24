import copy
import json
from types import SimpleNamespace

import pytest

from app.services.openai_chat import (
    draft_feedback_response_format,
    is_complete_draft_feedback,
    normalize_feedback,
)
from app.services.submission_data import get_reflection_data
from app.config import settings
from app.services.workflow_policy import (
    CORE_QUESTION_COUNT,
    MAX_GRAMMAR_CORRECTIONS,
    REFLECTION_QUESTIONS,
)


class _ReflectionQuery:
    def __init__(self, row):
        self.row = row

    def filter(self, *_args):
        return self

    def first(self):
        return self.row


class _ReflectionDb:
    def __init__(self, row):
        self.row = row

    def query(self, _model):
        return _ReflectionQuery(self.row)


def test_normalized_reflection_questions_are_json_compatible_lists():
    row = SimpleNamespace(
        revision=1,
        answers=[
            SimpleNamespace(question_index=index, answer_text=f"答案 {index + 1}")
            for index in range(len(REFLECTION_QUESTIONS))
        ],
        has_issue=False,
        issue_category=None,
        issue_description=None,
        photo_key=None,
        photo_original_name=None,
        submitted_at=None,
        updated_at=None,
    )

    result = get_reflection_data(_ReflectionDb(row), SimpleNamespace(id=1))

    assert isinstance(result["questions"], list)
    assert result["questions"] == list(REFLECTION_QUESTIONS)
    assert isinstance(result["answers"], list)


def _correction(index: int) -> dict[str, str]:
    return {
        "original": f"Incorrect sentence {index}.",
        "corrected": f"Corrected sentence {index}.",
        "explanation": f"第 {index} 個錯誤的說明。",
    }


def _feedback(corrections: list) -> dict:
    return {
        "questions": [
            {
                "index": 0,
                "grammar_corrections": corrections,
                "polished_sample": "This is a polished sample answer.",
            }
        ],
        "organization_suggestions": ["先回答核心問題。", "補上具體例子。", "最後簡短收尾。"],
    }


def test_draft_feedback_schema_caps_correction_count():
    response_format = draft_feedback_response_format(1)
    corrections_schema = response_format["json_schema"]["schema"]["properties"]["questions"]["items"][
        "properties"
    ]["grammar_corrections"]

    assert corrections_schema["maxItems"] == MAX_GRAMMAR_CORRECTIONS
    assert corrections_schema["type"] == "array"
    assert corrections_schema["items"]["required"] == ["original", "corrected", "explanation"]
    assert corrections_schema["items"]["additionalProperties"] is False


def test_complete_feedback_accepts_and_normalizes_more_than_three_corrections():
    feedback = _feedback([_correction(index) for index in range(5)])

    assert is_complete_draft_feedback(feedback, 1) is True

    normalized = normalize_feedback(
        copy.deepcopy(feedback),
        [{"question": "Tell me about yourself.", "text": "Draft answer."}],
    )
    assert len(normalized["questions"][0]["grammar_corrections"]) == 5
    assert normalized["questions"][0]["grammar_corrections"][4] == _correction(4)


def test_complete_feedback_accepts_cap_and_rejects_more():
    at_cap = _feedback([_correction(index) for index in range(MAX_GRAMMAR_CORRECTIONS)])
    over_cap = _feedback([_correction(index) for index in range(MAX_GRAMMAR_CORRECTIONS + 1)])

    assert is_complete_draft_feedback(at_cap, 1) is True
    assert is_complete_draft_feedback(over_cap, 1) is False


def test_worst_case_capped_feedback_fits_response_char_limit():
    """Four questions at the cap must not trip STAGE3_MAX_RESPONSE_CHARS."""
    correction = {
        "original": "x" * 120,
        "corrected": "x" * 120,
        "explanation": "說" * 40,
    }
    feedback = {
        "questions": [
            {
                "index": index,
                "grammar_corrections": [correction] * MAX_GRAMMAR_CORRECTIONS,
                "polished_sample": "word " * 100,
            }
            for index in range(CORE_QUESTION_COUNT)
        ],
        "organization_suggestions": ["建" * 80] * 5,
    }

    assert len(json.dumps(feedback, ensure_ascii=False)) < settings.STAGE3_MAX_RESPONSE_CHARS


def test_complete_feedback_accepts_empty_corrections():
    assert is_complete_draft_feedback(_feedback([]), 1) is True


@pytest.mark.parametrize(
    "invalid_correction",
    [
        "not an object",
        {"original": "Wrong.", "corrected": "Right."},
        {"original": "Wrong.", "corrected": "Right.", "explanation": "   "},
    ],
)
def test_complete_feedback_rejects_invalid_correction_objects(invalid_correction):
    assert is_complete_draft_feedback(_feedback([invalid_correction]), 1) is False
