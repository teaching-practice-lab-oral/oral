"""Word-level timing metadata for shadowing model audio."""
from __future__ import annotations

import hashlib
import logging
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass

from app.services import whisper

logger = logging.getLogger(__name__)

TIMING_VERSION = 2
SPEECH_SCOPE = "answer_only"
ANSWER_ONLY_KEY_FRAGMENT = "/shadowing_tts_answer_q"
MIN_ALIGNMENT_COVERAGE = 0.85
_WORD_RE = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*", re.UNICODE)


@dataclass(frozen=True)
class _Token:
    text: str
    start: int
    end: int
    normalized: str


def build_shadowing_tts_text(answer: dict, question_index: int) -> str:
    del question_index
    return str(answer.get("text", ""))


def is_answer_only_tts_key(key: str | None) -> bool:
    return bool(key and ANSWER_ONLY_KEY_FRAGMENT in key)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _normalize_word(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = normalized.replace("\u2019", "'").casefold()
    return "".join(character for character in normalized if character.isalnum())


def _tokenize(value: str) -> list[_Token]:
    tokens = []
    for match in _WORD_RE.finditer(value or ""):
        normalized = _normalize_word(match.group(0))
        if normalized:
            tokens.append(_Token(match.group(0), match.start(), match.end(), normalized))
    return tokens


def _clean_recognized_words(words: list[dict]) -> list[dict]:
    clean = []
    for item in words or []:
        normalized = _normalize_word(item.get("word", ""))
        start = item.get("start")
        end = item.get("end")
        if not normalized:
            continue
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        start = float(start)
        end = float(end)
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            continue
        clean.append({
            "normalized": normalized,
            "start": start,
            "end": end,
        })
    return clean


def _matching_word_indices(source: list[_Token], recognized: list[dict]) -> dict[int, int]:
    """Levenshtein-align source and recognized tokens, returning exact matches."""
    source_count = len(source)
    recognized_count = len(recognized)
    costs = [[0] * (recognized_count + 1) for _ in range(source_count + 1)]
    parents = [[""] * (recognized_count + 1) for _ in range(source_count + 1)]
    for i in range(1, source_count + 1):
        costs[i][0] = i
        parents[i][0] = "delete"
    for j in range(1, recognized_count + 1):
        costs[0][j] = j
        parents[0][j] = "insert"

    for i in range(1, source_count + 1):
        for j in range(1, recognized_count + 1):
            is_match = source[i - 1].normalized == recognized[j - 1]["normalized"]
            diagonal = costs[i - 1][j - 1] + (0 if is_match else 1)
            delete = costs[i - 1][j] + 1
            insert = costs[i][j - 1] + 1
            best = min(diagonal, delete, insert)
            costs[i][j] = best
            # Prefer an exact diagonal, then a substitution, so repeated words
            # remain anchored close to their spoken position.
            if diagonal == best:
                parents[i][j] = "match" if is_match else "substitute"
            elif delete == best:
                parents[i][j] = "delete"
            else:
                parents[i][j] = "insert"

    matches: dict[int, int] = {}
    i = source_count
    j = recognized_count
    while i > 0 or j > 0:
        operation = parents[i][j]
        if operation in {"match", "substitute"}:
            if operation == "match":
                matches[i - 1] = j - 1
            i -= 1
            j -= 1
        elif operation == "delete":
            i -= 1
        else:
            j -= 1
    return matches


def _interpolate_missing_timings(
    source_tokens: list[_Token],
    recognized: list[dict],
    matches: dict[int, int],
    answer_indices: list[int],
) -> dict[int, tuple[float, float]] | None:
    timings = {
        source_index: (
            recognized[recognized_index]["start"],
            recognized[recognized_index]["end"],
        )
        for source_index, recognized_index in matches.items()
    }
    matched_durations = [
        end - start
        for source_index, (start, end) in timings.items()
        if source_index in answer_indices and end > start
    ]
    typical_duration = statistics.median(matched_durations) if matched_durations else 0.3
    typical_duration = min(max(typical_duration, 0.08), 1.0)

    missing = [source_index for source_index in answer_indices if source_index not in timings]
    position = 0
    while position < len(missing):
        run = [missing[position]]
        while position + len(run) < len(missing) and missing[position + len(run)] == run[-1] + 1:
            run.append(missing[position + len(run)])
        position += len(run)

        previous_indices = [index for index in timings if index < run[0]]
        following_indices = [index for index in timings if index > run[-1]]
        previous_index = max(previous_indices) if previous_indices else None
        following_index = min(following_indices) if following_indices else None
        previous = timings[previous_index] if previous_index is not None else None
        following = timings[following_index] if following_index is not None else None

        if previous and following:
            lower = previous[1]
            upper = following[0]
            if upper <= lower:
                # Whisper occasionally emits a zero-duration word at the exact
                # boundary shared by its neighbours. The zero-duration entry is
                # filtered before alignment, leaving no literal gap to place the
                # canonical word. Borrow part of the following word's interval
                # (or, if necessary, the previous word's) instead of discarding
                # an otherwise high-confidence alignment.
                borrowed_start = max(previous[1], following[0])
                borrowed_duration = following[1] - borrowed_start
                if borrowed_duration > 0.02 * (len(run) + 1):
                    step = borrowed_duration / (len(run) + 1)
                    lower = borrowed_start
                    upper = borrowed_start + step * len(run)
                    timings[following_index] = (upper, following[1])
                else:
                    borrowed_end = min(previous[1], following[0])
                    borrowed_duration = borrowed_end - previous[0]
                    if borrowed_duration <= 0.02 * (len(run) + 1):
                        return None
                    step = borrowed_duration / (len(run) + 1)
                    timings[previous_index] = (previous[0], previous[0] + step)
                    lower = previous[0] + step
                    upper = borrowed_end
        elif previous:
            lower = previous[1]
            upper = lower + typical_duration * len(run)
        elif following:
            upper = following[0]
            lower = max(0.0, upper - typical_duration * len(run))
        else:
            return None

        step = (upper - lower) / len(run)
        for offset, source_index in enumerate(run):
            start = lower + step * offset
            end = lower + step * (offset + 1)
            if end <= start:
                return None
            timings[source_index] = (start, end)

    return timings


def align_answer_cues(
    spoken_text: str,
    answer_text: str,
    words: list[dict],
    minimum_coverage: float = MIN_ALIGNMENT_COVERAGE,
) -> list[dict] | None:
    """Align canonical answer text with recognized words, preserving display text."""
    if not answer_text or not spoken_text.endswith(answer_text):
        return None
    source_tokens = _tokenize(spoken_text)
    recognized = _clean_recognized_words(words)
    answer_offset = len(spoken_text) - len(answer_text)
    answer_indices = [
        index for index, token in enumerate(source_tokens) if token.start >= answer_offset
    ]
    if not source_tokens or not recognized or not answer_indices:
        return None

    matches = _matching_word_indices(source_tokens, recognized)
    matched_answer_count = sum(index in matches for index in answer_indices)
    if matched_answer_count / len(answer_indices) < minimum_coverage:
        return None

    timings = _interpolate_missing_timings(
        source_tokens,
        recognized,
        matches,
        answer_indices,
    )
    if timings is None:
        return None

    answer_tokens = [source_tokens[index] for index in answer_indices]
    cues = []
    previous_start = -1.0
    for position, (source_index, token) in enumerate(zip(answer_indices, answer_tokens)):
        start, end = timings[source_index]
        if start < previous_start or end <= start:
            return None
        relative_start = token.start - answer_offset
        relative_end = (
            answer_tokens[position + 1].start - answer_offset
            if position + 1 < len(answer_tokens)
            else len(answer_text)
        )
        if position == 0:
            relative_start = 0
        display_text = answer_text[relative_start:relative_end]
        if not display_text:
            return None
        cues.append({
            "text": display_text,
            "start": round(start, 3),
            "end": round(end, 3),
        })
        previous_start = start

    if "".join(cue["text"] for cue in cues) != answer_text:
        return None
    return cues


def unavailable_timing(audio_bytes: bytes, spoken_text: str, reason: str) -> dict:
    return {
        "version": TIMING_VERSION,
        "speech_scope": SPEECH_SCOPE,
        "status": "unavailable",
        "audio_sha256": _sha256_bytes(audio_bytes),
        "source_sha256": _sha256_text(spoken_text),
        "reason": reason,
        "cues": [],
    }


async def create_tts_timing(audio_bytes: bytes, spoken_text: str, answer_text: str) -> dict:
    """Transcribe generated speech and return cacheable timing metadata."""
    try:
        _, words = await whisper.transcribe_word_timestamps(
            audio_bytes,
            filename="shadowing-tts.mp3",
            # Whisper prompts are token-limited; a bounded canonical prefix is
            # enough to stabilize names and contractions without rejecting a
            # long student answer.
            prompt=spoken_text[:700],
        )
    except Exception:
        logger.warning("Could not generate word timestamps for shadowing TTS", exc_info=True)
        return unavailable_timing(audio_bytes, spoken_text, "transcription_failed")

    cues = align_answer_cues(spoken_text, answer_text, words)
    if cues is None:
        return unavailable_timing(audio_bytes, spoken_text, "alignment_failed")
    return {
        "version": TIMING_VERSION,
        "speech_scope": SPEECH_SCOPE,
        "status": "ready",
        "audio_sha256": _sha256_bytes(audio_bytes),
        "source_sha256": _sha256_text(spoken_text),
        "cues": cues,
    }


def timing_matches_source(timing: dict | None, spoken_text: str) -> bool:
    return bool(
        isinstance(timing, dict)
        and timing.get("version") == TIMING_VERSION
        and timing.get("speech_scope") == SPEECH_SCOPE
        and timing.get("source_sha256") == _sha256_text(spoken_text)
        and timing.get("status") in {"ready", "unavailable"}
    )
