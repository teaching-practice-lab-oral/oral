import asyncio
from dataclasses import dataclass
from enum import Enum

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.services import worker_client

_client: AsyncOpenAI | None = None
_tts_semaphore = asyncio.Semaphore(settings.TTS_MAX_CONCURRENCY)
MAX_TTS_INPUT_CHARS = 4096


class SpeechProfile(str, Enum):
    ROLEPLAY = "roleplay"
    SHADOWING = "shadowing"


@dataclass(frozen=True)
class SpeechProfileConfig:
    voice: str
    speed: float
    instructions: str


SPEECH_PROFILES = {
    SpeechProfile.ROLEPLAY: SpeechProfileConfig(
        voice="cedar",
        speed=1.0,
        instructions=(
            "Speak as a professional but approachable job interviewer in Taiwan conducting an English interview. "
            "Use natural conversational English with subtle, context-appropriate intonation and brief realistic "
            "pauses. Emphasize the key words in each question. Sound attentive, calm, and mildly encouraging. Do "
            "not sound like an announcer, textbook narrator, language-learning recording, or automated phone "
            "system. Read only the supplied text exactly; do not add, remove, or paraphrase any words."
        ),
    ),
    SpeechProfile.SHADOWING: SpeechProfileConfig(
        voice="marin",
        speed=1.0,
        instructions=(
            "Read the supplied English answer exactly as written for an English learner to shadow. Use clear, "
            "natural pronunciation at a normal 1.0x pace. Keep a realistic conversational rhythm while making "
            "content words, phrase boundaries, and brief pauses easy to hear. Prioritize intelligibility without "
            "over-enunciating or sounding robotic. Do not explain, spell out, add, remove, or paraphrase any words, "
            "and do not imitate a particular accent."
        ),
    ),
}


def validate_speech_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("TTS text must not be empty")
    if len(text) > MAX_TTS_INPUT_CHARS:
        raise ValueError(f"TTS text must not exceed {MAX_TTS_INPUT_CHARS} characters")
    return text


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0),
        )
    return _client


async def generate_speech_local(text: str, profile: SpeechProfile) -> bytes:
    """Generate speech audio locally through OpenAI TTS. Returns MP3 bytes."""
    text = validate_speech_text(text)
    profile_config = SPEECH_PROFILES[profile]
    async with _tts_semaphore:
        client = _get_client()
        response = await client.audio.speech.create(
            model=settings.OPENAI_TTS_MODEL,
            voice=profile_config.voice,
            input=text,
            response_format="mp3",
            speed=profile_config.speed,
            instructions=profile_config.instructions,
        )
    return response.content


async def generate_speech(text: str, profile: SpeechProfile) -> bytes:
    """Generate speech audio, optionally delegating stateless work to the CHT worker."""
    text = validate_speech_text(text)
    worker_audio = await worker_client.generate_speech(text, profile=profile.value)
    if worker_audio is not None:
        return worker_audio
    return await generate_speech_local(text, profile)
