import re
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
