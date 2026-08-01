import re
import unicodedata
from fastapi import HTTPException, status

_CJK_RE = re.compile(r'[一-鿿㐀-䶿豈-﫿]')

_CODE_PATTERNS = re.compile(
    r'```|'
    r'\bdef\s+\w+\s*\(|'
    r'\bclass\s+\w+\s*[:(]|'
    r'\bimport\s+\w+|'
    r'\bfrom\s+\w+\s+import\b|'
    r'\bfunction\s*\w*\s*\(|'
    r'<\s*script\b|'
    r'\bpublic\s+(?:static\s+)?(?:void|class|int|String)\b|'
    r'#include\s*<',
    re.IGNORECASE,
)

_MIN_LENGTH = 30
_MAX_LENGTH = 2000
_CHINESE_THRESHOLD = 0.3

_DISALLOWED_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]"
)
_NON_LATIN_SCRIPT_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af"
    r"\u0400-\u052f\u0600-\u06ff]"
)
_TRANSCRIPT_MAX_LENGTH = 12000

_PROMPT_OVERRIDE_RE = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,80}"
    r"\b(?:previous|prior|earlier|above|system|developer)\b.{0,40}"
    r"\b(?:instruction|prompt|message|rule)s?\b",
    re.IGNORECASE | re.DOTALL,
)
_SYSTEM_PROMPT_REQUEST_RE = re.compile(
    r"\b(?:reveal|show|print|repeat|display|provide|tell\s+me)\b.{0,60}"
    r"\b(?:system|developer)\b.{0,30}\b(?:prompt|message|instruction)s?\b",
    re.IGNORECASE | re.DOTALL,
)
_ROLE_ESCAPE_RE = re.compile(
    r"\b(?:you\s+are\s+now|act\s+as|switch\s+(?:your\s+)?role|"
    r"break\s+character|leave\s+(?:the\s+)?interviewer\s+role|"
    r"you\s+are\s+no\s+longer\s+(?:an?\s+|the\s+)?interviewer)\b",
    re.IGNORECASE,
)
_FORCED_OUTPUT_RE = re.compile(
    r"\b(?:respond|reply|return|output|write|execute|run)\s+(?:with\s+)?exactly\b|"
    r"\binstead\s+(?:write|return|output|execute|run)\b",
    re.IGNORECASE,
)
_DIRECT_CODE_OR_TOOL_RE = re.compile(
    r"(?:^|[.!?;:,]\s+|\bplease\s+)"
    r"(?:(?:please)\s+|(?:(?:can|could|would)\s+you\s+))?"
    r"(?:"
    r"(?:write|generate|output|return|provide|show|give(?:\s+me)?)\b.{0,50}"
    r"\b(?:python|javascript|shell|source)?\s*code\b|"
    r"(?:run|execute)\b.{0,50}\b(?:shell\s+command|command|script|curl|wget)\b|"
    r"(?:open|visit|browse(?:\s+to)?|follow|navigate(?:\s+to)?|access)"
    r"\b.{0,100}\b(?:https?://|www\.)|"
    r"(?:use|call|invoke|launch|access)\b.{0,40}\b(?:tool|function|api)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)


def normalize_user_text(value: str, *, field_name: str = "欄位") -> str:
    """Normalize ordinary user-authored text and reject invisible controls.

    Passwords deliberately do not use this function: changing their Unicode or
    whitespace would change the credential supplied by the user.
    """
    normalized = unicodedata.normalize("NFC", str(value or ""))
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n").strip()
    if _DISALLOWED_CONTROL_RE.search(normalized):
        raise ValueError(f"{field_name} 包含不允許的控制字元")
    return normalized


def normalize_http_text(value: str | None, *, field_name: str) -> str | None:
    """Apply ordinary-text rules to query/path fields with HTTP 422 semantics."""
    if value is None:
        return None
    try:
        return normalize_user_text(value, field_name=field_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def transcript_rejection_reason(transcript: str | None) -> str | None:
    """Return a stable rejection reason for high-confidence roleplay abuse.

    This is intentionally narrow.  It catches direct model-control commands,
    while the prompt/data boundary and server-owned interviewer templates remain
    the final protection when natural-language detection misses a paraphrase.
    """
    try:
        text = normalize_user_text(transcript or "", field_name="語音逐字稿")
    except ValueError:
        return "invalid_controls"
    if not text:
        return "empty"
    if len(text) > _TRANSCRIPT_MAX_LENGTH:
        return "too_long"

    override_match = _PROMPT_OVERRIDE_RE.search(text)
    if override_match:
        prefix = text[max(0, override_match.start() - 16):override_match.start()].lower()
        if not re.search(
            r"\b(?:never|don't|didn't|wouldn't|shouldn't|couldn't|won't|can't|"
            r"(?:do|did|would|should|could|will|can)\s+not)\s*$",
            prefix,
        ):
            return "prompt_override"
    if _SYSTEM_PROMPT_REQUEST_RE.search(text):
        return "system_prompt_request"
    if _ROLE_ESCAPE_RE.search(text):
        return "role_escape"
    if _FORCED_OUTPUT_RE.search(text):
        return "forced_output"
    if _DIRECT_CODE_OR_TOOL_RE.search(text):
        return "tool_or_code_request"

    non_latin_count = len(_NON_LATIN_SCRIPT_RE.findall(text))
    letter_count = sum(character.isalpha() for character in text)
    if non_latin_count >= 4 and non_latin_count / max(letter_count, 1) >= 0.2:
        return "english_only"
    return None


def validate_roleplay_transcript(transcript: str | None) -> str:
    """Normalize a transcript or reject it before persistence/LLM reuse."""
    reason = transcript_rejection_reason(transcript)
    if reason is not None:
        message = (
            "Please answer the current interview question in English."
            if reason == "english_only"
            else "Let's stay focused on the interview. Please answer the current question in English."
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "roleplay_response_rejected",
                "message": message,
                "replay_current_question": True,
            },
        )
    return normalize_user_text(transcript or "", field_name="語音逐字稿")


def validate_draft_text(text: str) -> None:
    """Reject drafts that are too short/long, mostly Chinese, or contain code."""
    text = text.strip()

    if len(text) < _MIN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"草稿內容太短，請輸入至少 {_MIN_LENGTH} 個字元的英文面試答案。",
        )
    if len(text) > _MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"草稿內容過長（上限 {_MAX_LENGTH} 字元）。",
        )

    non_space = re.sub(r'\s', '', text)
    if non_space:
        cjk_count = len(_CJK_RE.findall(non_space))
        if cjk_count / len(non_space) > _CHINESE_THRESHOLD:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="草稿請以英文撰寫，偵測到大量中文內容。",
            )

    if _CODE_PATTERNS.search(text):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="草稿不應包含程式碼，請提交英文面試答案。",
        )
