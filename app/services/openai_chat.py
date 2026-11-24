import asyncio
import json
from typing import Any, AsyncIterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import AsyncOpenAI, APIError

from app.config import settings
from app.services.workflow_policy import MAX_GRAMMAR_CORRECTIONS

_openai_semaphore = asyncio.Semaphore(settings.OPENAI_MAX_CONCURRENCY)


def extract_json_object(text: str) -> dict | None:
    """Find and return the last valid JSON object in text, handling concatenated or partial JSON."""
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Scan for top-level JSON objects, properly handling strings with braces
    best = None
    i = 0
    while i < len(text):
        if text[i] != '{':
            i += 1
            continue
        start = i
        depth = 0
        in_string = False
        escape = False
        j = i
        while j < len(text):
            c = text[j]
            if escape:
                escape = False
            elif c == '\\' and in_string:
                escape = True
            elif c == '"':
                in_string = not in_string
            elif not in_string:
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[start:j + 1])
                            if isinstance(obj, dict):
                                best = obj
                        except json.JSONDecodeError:
                            pass
                        i = j + 1
                        break
            j += 1
        else:
            break
    return best


def _normalize_corrections(corrections: list) -> list:
    """Normalise a grammar_corrections list, tolerating variant field names."""
    if not isinstance(corrections, list):
        return []
    normalized = []
    for c in corrections:
        if not isinstance(c, dict):
            continue
        original = (c.get("original") or c.get("sentence") or c.get("error") or
                    c.get("before") or c.get("original_sentence") or c.get("incorrect") or "")
        corrected = (c.get("corrected") or c.get("correction") or c.get("fix") or
                     c.get("fixed") or c.get("after") or c.get("revised") or c.get("correct") or "")
        explanation = (c.get("explanation") or c.get("reason") or c.get("note") or
                       c.get("comment") or c.get("feedback") or "")
        if original or corrected:
            normalized.append({"original": str(original), "corrected": str(corrected), "explanation": str(explanation)})
    return normalized


def normalize_feedback(data: dict, answers: list[dict] | None = None) -> dict:
    """Normalise feedback and bind each AI item to the immutable input question.

    The model is asked to preserve zero-based indices, but a malformed or
    one-based response must never make the UI display one answer underneath a
    different question.  When the returned indices are not a complete unique
    set, array order is used as the safe fallback.
    """
    if not isinstance(data, dict):
        return data
    if "questions" in data and isinstance(data["questions"], list):
        for q in data["questions"]:
            if isinstance(q, dict) and "grammar_corrections" in q:
                q["grammar_corrections"] = _normalize_corrections(q["grammar_corrections"])
        if answers:
            expected_indices = set(range(len(answers)))
            returned_by_index: dict[int, dict] = {}
            for q in data["questions"]:
                if not isinstance(q, dict):
                    continue
                try:
                    index = int(q.get("index"))
                except (TypeError, ValueError):
                    continue
                if index in expected_indices and index not in returned_by_index:
                    returned_by_index[index] = q
            indices_are_reliable = set(returned_by_index) == expected_indices
            positional = [q for q in data["questions"] if isinstance(q, dict)]
            bound_questions = []
            for index, answer in enumerate(answers):
                if indices_are_reliable:
                    item = dict(returned_by_index[index])
                else:
                    item = dict(positional[index]) if index < len(positional) else {}
                item["index"] = index
                item["question"] = str(answer.get("question") or "")
                item["grammar_corrections"] = _normalize_corrections(item.get("grammar_corrections", []))
                item["polished_sample"] = str(item.get("polished_sample") or "")
                bound_questions.append(item)
            data["questions"] = bound_questions
    elif "grammar_corrections" in data:
        data["grammar_corrections"] = _normalize_corrections(data.get("grammar_corrections", []))
    suggestions = data.get("organization_suggestions", [])
    if isinstance(suggestions, list):
        data["organization_suggestions"] = [str(s) for s in suggestions if s]
    return data


def draft_feedback_response_format(question_count: int) -> dict[str, Any]:
    """Strict Structured Outputs contract for per-question Draft 1 feedback."""
    if question_count < 1:
        raise ValueError("question_count must be positive")
    correction = {
        "type": "object",
        "properties": {
            "original": {"type": "string", "minLength": 1, "maxLength": 2000},
            "corrected": {"type": "string", "minLength": 1, "maxLength": 2000},
            "explanation": {"type": "string", "minLength": 1, "maxLength": 2000},
        },
        "required": ["original", "corrected", "explanation"],
        "additionalProperties": False,
    }
    question = {
        "type": "object",
        "properties": {
            "index": {
                "type": "integer",
                "minimum": 0,
                "maximum": question_count - 1,
            },
            "grammar_corrections": {
                "type": "array",
                "items": correction,
                "maxItems": MAX_GRAMMAR_CORRECTIONS,
            },
            "polished_sample": {"type": "string", "minLength": 1, "maxLength": 4000},
        },
        "required": ["index", "grammar_corrections", "polished_sample"],
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "draft_feedback",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": question,
                        "minItems": question_count,
                        "maxItems": question_count,
                    },
                    "organization_suggestions": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                        "minItems": 3,
                        "maxItems": 5,
                    },
                },
                "required": ["questions", "organization_suggestions"],
                "additionalProperties": False,
            },
        },
    }


def is_complete_draft_feedback(data: Any, question_count: int) -> bool:
    """Reject incomplete/refused/truncated output before it reaches persistence."""
    if not isinstance(data, dict) or set(data) != {"questions", "organization_suggestions"}:
        return False
    questions = data.get("questions")
    suggestions = data.get("organization_suggestions")
    if not isinstance(questions, list) or len(questions) != question_count:
        return False
    if not isinstance(suggestions, list) or not 3 <= len(suggestions) <= 5 or not all(
        isinstance(item, str) and 1 <= len(item.strip()) <= 1000 for item in suggestions
    ):
        return False
    seen_indices: set[int] = set()
    for item in questions:
        if not isinstance(item, dict) or set(item) != {"index", "grammar_corrections", "polished_sample"}:
            return False
        index = item.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < question_count:
            return False
        seen_indices.add(index)
        corrections = item.get("grammar_corrections")
        if not isinstance(corrections, list) or len(corrections) > MAX_GRAMMAR_CORRECTIONS:
            return False
        if (
            not isinstance(item.get("polished_sample"), str)
            or not 1 <= len(item["polished_sample"].strip()) <= 4000
        ):
            return False
        if not all(
            isinstance(correction, dict)
            and set(correction) == {"original", "corrected", "explanation"}
            and all(
                isinstance(correction.get(field), str)
                and 1 <= len(correction[field].strip()) <= 2000
                for field in ("original", "corrected", "explanation")
            )
            for correction in corrections
        ):
            return False
    return seen_indices == set(range(question_count))


_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=5.0),
        )
    return _client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(APIError),
    reraise=True,
)
async def chat_completion(system_prompt: str, user_content: str) -> str:
    async with _openai_semaphore:
        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
    return response.choices[0].message.content


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(APIError),
    reraise=True,
)
async def chat_completion_json(
    system_prompt: str,
    user_content: str,
    max_chars: int = settings.STAGE3_MAX_RESPONSE_CHARS,
    temperature: float | None = None,
    response_format: dict[str, Any] | None = None,
) -> Any:
    """Call in JSON mode and parse the response."""
    async with _openai_semaphore:
        client = _get_client()
        kwargs: dict = dict(
            model=settings.OPENAI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format=response_format or {"type": "json_object"},
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = await client.chat.completions.create(**kwargs)
    raw = response.choices[0].message.content
    if max_chars and len(raw) > max_chars:
        raise ValueError(f"AI 輸出超過 {max_chars} 字元上限（實際：{len(raw)}），已拒絕使用此回應")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        extracted = extract_json_object(raw)
        return extracted if extracted else {"raw": raw}


async def chat_completion_json_stream(
    system_prompt: str,
    user_content: str,
    max_chars: int = settings.STAGE3_MAX_RESPONSE_CHARS,
    response_format: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Stream JSON response token by token. Aborts the connection if output exceeds max_chars."""
    async with _openai_semaphore:
        client = _get_client()
        stream = await client.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format=response_format or {"type": "json_object"},
            stream=True,
        )
        char_count = 0
        try:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    char_count += len(delta)
                    if max_chars and char_count > max_chars:
                        raise ValueError(f"AI 輸出超過 {max_chars} 字元上限，已強制中止請求")
                    yield delta
        finally:
            await stream.close()
