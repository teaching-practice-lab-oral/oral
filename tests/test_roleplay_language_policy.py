from app.prompts import STAGE6_ROLEPLAY_POLICY, STAGE6_SECRET_QUESTION_POLICY
from app.services.roleplay_policy import (
    question_request,
    validated_question,
    validated_secret_question,
)


CORE_QUESTIONS = [
    "Please introduce yourself.",
    "Why are you interested in this position?",
    "What is your greatest strength?",
    "What skill would you like to improve?",
]


def test_roleplay_prompts_do_not_seed_repetitive_concrete_wording():
    request = question_request(0, CORE_QUESTIONS[0], "")
    combined = " ".join(
        (request, STAGE6_ROLEPLAY_POLICY, STAGE6_SECRET_QUESTION_POLICY)
    ).lower()

    assert "concrete" not in combined
    assert "do not automatically" in combined
    assert "vary the wording" in combined


def test_generated_concrete_probe_falls_back_to_teacher_question():
    question, source_index = validated_question(
        "Please introduce yourself and give one concrete example from your experience.",
        CORE_QUESTIONS,
        0,
    )

    assert question == CORE_QUESTIONS[0]
    assert source_index == 0


def test_teacher_authored_concrete_word_is_preserved():
    questions = [
        "Please give one concrete example of your teamwork.",
        *CORE_QUESTIONS[1:],
    ]
    generated = "Could you give one concrete example of your teamwork?"

    question, source_index = validated_question(generated, questions, 0)

    assert question == generated
    assert source_index == 0


def test_secret_question_with_concrete_word_uses_varied_fallback():
    question = validated_secret_question(
        "Can you share one concrete example of that challenge?",
        CORE_QUESTIONS,
    )

    assert "concrete" not in question.lower()
    assert "one situation" in question.lower()
