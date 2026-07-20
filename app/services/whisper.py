import asyncio
import io
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import AsyncOpenAI, APIError

from app.config import settings

_client: AsyncOpenAI | None = None
_whisper_semaphore = asyncio.Semaphore(settings.AUDIO_PROCESSING_MAX_CONCURRENCY)

PAUSE_THRESHOLD = 0.5
LONG_PAUSE_THRESHOLD = 1.5
VERY_LONG_PAUSE_THRESHOLD = 3.0


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=5.0),
        )
    return _client


def compute_fluency_metrics(words: list) -> dict:
    clean_words = []
    for word in words or []:
        text = str(word.get("word", "")).strip()
        start = word.get("start")
        end = word.get("end")
        if not text or not any(ch.isalnum() for ch in text):
            continue
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        if end <= start:
            continue
        clean_words.append({"word": text, "start": float(start), "end": float(end)})

    if len(clean_words) < 2:
        return {}
    total_words = len(clean_words)
    first_start = clean_words[0]["start"]
    last_end = clean_words[-1]["end"]
    duration = last_end - first_start
    if duration <= 0:
        return {}
    wpm = round(total_words / (duration / 60))
    pauses: list[float] = []
    for i in range(1, len(clean_words)):
        gap = clean_words[i]["start"] - clean_words[i - 1]["end"]
        if gap >= PAUSE_THRESHOLD:
            pauses.append(gap)
    long_pauses = [p for p in pauses if p >= LONG_PAUSE_THRESHOLD]
    very_long_pauses = [p for p in pauses if p >= VERY_LONG_PAUSE_THRESHOLD]
    total_pause_seconds = sum(pauses)
    speaking_seconds = max(duration - total_pause_seconds, 0)
    articulation_wpm = round(total_words / (speaking_seconds / 60)) if speaking_seconds > 0 else wpm
    rounded_pauses = [round(p, 2) for p in pauses]
    return {
        "wpm": wpm,
        "articulation_wpm": articulation_wpm,
        "total_words": total_words,
        "duration_seconds": round(duration, 1),
        "pause_count": len(pauses),
        "long_pause_count": len(long_pauses),
        "very_long_pause_count": len(very_long_pauses),
        "avg_pause_seconds": round(total_pause_seconds / len(pauses), 2) if pauses else 0,
        "longest_pause_seconds": round(max(pauses), 2) if pauses else 0,
        "total_pause_seconds": round(total_pause_seconds, 2),
        "pause_seconds_ratio": round(total_pause_seconds / duration, 2),
        "pauses_per_minute": round(len(pauses) / (duration / 60), 1),
        "long_pauses_per_minute": round(len(long_pauses) / (duration / 60), 1),
        "pause_threshold_seconds": PAUSE_THRESHOLD,
        "long_pause_threshold_seconds": LONG_PAUSE_THRESHOLD,
        "very_long_pause_threshold_seconds": VERY_LONG_PAUSE_THRESHOLD,
        "pause_durations_seconds": rounded_pauses,
    }


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(APIError),
    reraise=True,
)
async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    client = _get_client()
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename
    async with _whisper_semaphore:
        response = await client.audio.transcriptions.create(
            model=settings.OPENAI_WHISPER_MODEL,
            file=audio_file,
            language="en",
        )
    return response.text


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(APIError),
    reraise=True,
)
async def transcribe_word_timestamps(
    audio_bytes: bytes,
    filename: str = "audio.webm",
    prompt: str | None = None,
) -> tuple[str, list[dict]]:
    """Return the transcript and normalized word-level timestamps."""
    client = _get_client()
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename
    request = {
        "model": settings.OPENAI_WHISPER_MODEL,
        "file": audio_file,
        "language": "en",
        "response_format": "verbose_json",
        "timestamp_granularities": ["word"],
    }
    if prompt:
        request["prompt"] = prompt
    async with _whisper_semaphore:
        response = await client.audio.transcriptions.create(**request)
    transcript = response.text
    words = getattr(response, "words", None) or []
    words_list = [
        {"word": w.get("word", w) if isinstance(w, dict) else w.word,
         "start": w.get("start", 0) if isinstance(w, dict) else w.start,
         "end": w.get("end", 0) if isinstance(w, dict) else w.end}
        for w in words
    ]
    return transcript, words_list


async def transcribe_with_metrics(audio_bytes: bytes, filename: str = "audio.webm") -> tuple[str, dict]:
    """Returns (transcript, fluency_metrics). Falls back to plain transcript if timestamps unavailable."""
    transcript, words_list = await transcribe_word_timestamps(audio_bytes, filename)
    metrics = compute_fluency_metrics(words_list)
    return transcript, metrics
