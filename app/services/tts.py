import asyncio

import httpx
from openai import AsyncOpenAI
from app.config import settings
from app.services import worker_client

_client: AsyncOpenAI | None = None
_tts_semaphore = asyncio.Semaphore(settings.TTS_MAX_CONCURRENCY)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=5.0),
        )
    return _client


async def generate_speech_local(text: str, voice: str | None = None, speed: float | None = None) -> bytes:
    """Generate speech audio locally through OpenAI TTS. Returns MP3 bytes."""
    async with _tts_semaphore:
        client = _get_client()
        response = await client.audio.speech.create(
            model=settings.OPENAI_TTS_MODEL,
            voice=voice or settings.TTS_VOICE,
            input=text,
            response_format="mp3",
            speed=speed if speed is not None else settings.TTS_SPEED,
        )
    return response.content


async def generate_speech(text: str, voice: str | None = None, speed: float | None = None) -> bytes:
    """Generate speech audio, optionally delegating stateless work to the CHT worker."""
    worker_audio = await worker_client.generate_speech(text, voice=voice, speed=speed)
    if worker_audio is not None:
        return worker_audio
    return await generate_speech_local(text, voice=voice, speed=speed)
