from types import SimpleNamespace

from app.services.submission_data import get_reflection_data
from app.services.workflow_policy import REFLECTION_QUESTIONS


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
