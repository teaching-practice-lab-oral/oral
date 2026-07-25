"""Pure roleplay question-matching and response-relevance policy."""

import re
import logging
from difflib import SequenceMatcher

from app.question_sets import CUSTOM_QUESTION_MAX_CHARS, contains_non_latin_script
from app.services.workflow_policy import (
    CORE_QUESTION_COUNT,
    MAX_ROLEPLAY_TURNS,
    SECRET_QUESTION_SOURCE_INDEX,
)


logger = logging.getLogger(__name__)
_GUARDRAIL_REASK_MARKERS = (
    "please answer in english",
    "let's stay focused on the interview",
)
_SECRET_QUESTION_FALLBACK = (
    "Please choose one situation you mentioned and explain the difficulty "
    "you personally faced, what you did, and what result followed?"
)
_CONCRETE_WORD = re.compile(r"\bconcrete\b", re.IGNORECASE)


def _uses_unrequested_concrete_word(text: str, canonical_question: str | None = None) -> bool:
    return bool(
        _CONCRETE_WORD.search(text)
        and not _CONCRETE_WORD.search(canonical_question or "")
    )


def _normalize_interviewer_question(text: str | None) -> str:
    normalized = (text or "").lower().replace("’", "'")
    for phrase in ("let's stay focused on the interview", "please answer in english"):
        normalized = normalized.replace(phrase, " ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


_QUESTION_STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "briefly", "can",
    "could", "for", "from", "have", "interview", "please", "question",
    "tell", "thank", "thanks", "that", "the", "this", "today", "you", "your",
}


def _question_terms(text: str | None) -> set[str]:
    return {
        token
        for token in _normalize_interviewer_question(text).split()
        if len(token) > 2 and token not in _QUESTION_STOP_WORDS
    }


def _token_overlap_score(current_question: str | None, next_question: str | None) -> float:
    current_terms = _question_terms(current_question)
    next_terms = _question_terms(next_question)
    if not current_terms or not next_terms:
        return 0
    return len(current_terms & next_terms) / min(len(current_terms), len(next_terms))


def _best_interview_question_match(question: str | None, interview_questions) -> int | None:
    if not interview_questions:
        return None
    best_index = None
    best_score = 0.0
    for index, candidate in enumerate(interview_questions):
        normalized_question = _normalize_interviewer_question(question)
        normalized_candidate = _normalize_interviewer_question(str(candidate))
        if not normalized_question or not normalized_candidate:
            continue
        score = max(
            SequenceMatcher(None, normalized_question, normalized_candidate).ratio(),
            _token_overlap_score(normalized_question, normalized_candidate),
        )
        if score > best_score:
            best_index = index
            best_score = score
    return best_index if best_score >= 0.72 else None


def match_interview_question_index(question: str | None, core_questions) -> int | None:
    """Return the canonical index matching a natural interviewer paraphrase."""
    return _best_interview_question_match(question, core_questions)


def attach_source_indices(turns: list[dict], core_questions: list[str]) -> bool:
    changed = False
    for turn in turns:
        if turn.get("source_question_index") is not None:
            continue
        matched = match_interview_question_index(turn.get("interviewer_question"), core_questions)
        turn["source_question_index"] = matched if matched is not None else min(
            max(int(turn.get("turn_number", 1)) - 1, 0), len(core_questions) - 1
        )
        changed = True
    return changed


def expected_next_source_index(turns: list[dict], core_questions: list[str]) -> int:
    used = {turn.get("source_question_index") for turn in turns if turn.get("source_question_index") is not None}
    return next((index for index in range(len(core_questions)) if index not in used), len(core_questions) - 1)


def answered_core_source_indices(turns: list[dict]) -> set[int]:
    return {
        int(turn["source_question_index"])
        for turn in turns
        if turn.get("source_question_index") is not None
        and 0 <= int(turn["source_question_index"]) < CORE_QUESTION_COUNT
        and turn.get("student_transcript")
    }


def all_core_questions_answered(turns: list[dict], core_questions: list[str]) -> bool:
    return answered_core_source_indices(turns) == set(range(len(core_questions)))


def secret_question_exists(turns: list[dict]) -> bool:
    return any(turn.get("source_question_index") == SECRET_QUESTION_SOURCE_INDEX for turn in turns)


def secret_question_answered(turns: list[dict]) -> bool:
    return any(
        turn.get("source_question_index") == SECRET_QUESTION_SOURCE_INDEX and turn.get("student_transcript")
        for turn in turns
    )


def all_required_questions_answered(turns: list[dict], core_questions: list[str]) -> bool:
    return all_core_questions_answered(turns, core_questions) and secret_question_answered(turns)


def can_add_guardrail_reask(turns: list[dict], core_questions: list[str]) -> bool:
    used = {turn.get("source_question_index") for turn in turns if turn.get("source_question_index") is not None}
    missing_core_count = len(set(range(len(core_questions))) - used)
    missing_secret_count = 0 if secret_question_exists(turns) else 1
    return MAX_ROLEPLAY_TURNS - len(turns) > missing_core_count + missing_secret_count


def question_request(expected_index: int, core_question: str, context: str) -> str:
    return (
        f"Ask core question {expected_index + 1} now. Preserve this intent: {core_question}\n"
        "Keep it as one natural question. Use the core question as written unless a small "
        "spoken-English adjustment is needed. Do not automatically append an evidence probe. "
        "Only when the core intent requires more detail, ask about one fitting element such as "
        "a situation, the candidate's own action, reasoning, difficulty, or result. Vary the "
        "wording across the interview and do not repeat a stock phrase. "
        "Respond in English only; do not use Chinese or any other non-Latin script. "
        "Do not ask any other question.\n" + context
    )


def validated_question(
    generated: str | None,
    core_questions: list[str],
    expected_index: int,
    *,
    previous_index: int | None = None,
    allow_reask: bool = True,
) -> tuple[str, int]:
    text = (generated or "").strip()
    if len(text) > CUSTOM_QUESTION_MAX_CHARS or contains_non_latin_script(text):
        logger.warning("Roleplay question %s was invalid; using canonical fallback", expected_index)
        return core_questions[expected_index], expected_index
    if _uses_unrequested_concrete_word(text, core_questions[expected_index]):
        logger.warning(
            "Roleplay question %s used repetitive probe wording; using canonical fallback",
            expected_index,
        )
        return core_questions[expected_index], expected_index
    matched = match_interview_question_index(text, core_questions)
    if matched == expected_index:
        return text, matched
    lowered = text.lower().replace("’", "'")
    if allow_reask and previous_index is not None and matched == previous_index and any(
        marker in lowered for marker in _GUARDRAIL_REASK_MARKERS
    ):
        return text, previous_index
    logger.warning(
        "Roleplay question did not match expected core question %s; using canonical fallback (matched=%s)",
        expected_index,
        matched,
    )
    return core_questions[expected_index], expected_index


def validated_secret_question(generated: str | None, core_questions: list[str]) -> str:
    text = " ".join((generated or "").strip().split())
    if contains_non_latin_script(text) or _uses_unrequested_concrete_word(text):
        logger.warning(
            "Generated verification question violated language policy; using fallback"
        )
        return _SECRET_QUESTION_FALLBACK
    if (
        not text
        or len(text) > CUSTOM_QUESTION_MAX_CHARS
        or match_interview_question_index(text, core_questions) is not None
    ):
        return _SECRET_QUESTION_FALLBACK
    return text


def _is_repeated_interviewer_question(
    current_question: str | None,
    next_question: str | None,
    interview_questions=None,
) -> bool:
    current = _normalize_interviewer_question(current_question)
    next_ = _normalize_interviewer_question(next_question)
    if not current or not next_:
        return False
    if current == next_ or (len(current) >= 12 and current in next_) or (len(next_) >= 12 and next_ in current):
        return True
    if SequenceMatcher(None, current, next_).ratio() >= 0.9:
        return True
    if _token_overlap_score(current, next_) >= 0.82:
        return True
    current_match = _best_interview_question_match(current, interview_questions)
    next_match = _best_interview_question_match(next_, interview_questions)
    return current_match is not None and current_match == next_match


def _excerpt(text: str | None, limit: int = 160) -> str:
    value = re.sub(r"\s+", " ", (text or "[no response]").strip())
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def build_relevance_block(turns, core_questions=None) -> str:
    """Summarize interviewer re-asks for the qualitative report prompt."""
    events = []
    for index, turn in enumerate(turns[:-1]):
        next_turn = turns[index + 1]
        current_source = turn.get("source_question_index")
        next_source = next_turn.get("source_question_index")
        same_source = current_source is not None and next_source is not None and current_source == next_source
        if not same_source and not _is_repeated_interviewer_question(
            turn.get("interviewer_question"), next_turn.get("interviewer_question"), core_questions
        ):
            continue
        turn_number = turn.get("turn_number", index + 1)
        next_turn_number = next_turn.get("turn_number", turn_number + 1)
        events.append(
            f"- 第 {turn_number} 輪回答後，面試官在第 {next_turn_number} 輪回到同一題；"
            f"這是面試官判定第 {turn_number} 輪回答未充分回應題目核心、未依要求使用英文，或偏離面試任務的訊號。"
            f"第 {turn_number} 輪學生回答摘錄：「{_excerpt(turn.get('student_transcript'))}」"
        )
    lines = ["", "=== 回應切題性事件（由面試官重問訊號自動偵測）==="]
    if events:
        lines.extend(events)
        lines.append("請在 Pragmatics、內容邏輯與面試策略回饋中明確指出上述面試官重問訊號；不要只用流暢度或語法分數解釋。")
    else:
        lines.append("未偵測到相鄰輪次中面試官回到同一題。")
    return "\n".join(lines)
