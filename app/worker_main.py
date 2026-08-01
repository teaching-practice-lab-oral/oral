"""Internal stateless worker app for CHT/Taiwan VM audio offload."""
import base64
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.middleware import BearerPathAuthMiddleware, RequestBodyLimitMiddleware
from app.services.tts import MAX_TTS_INPUT_CHARS, SpeechProfile, generate_speech_local

app = FastAPI(
    title="Oral CHT Worker",
    description="Internal stateless audio/TTS worker. Do not expose public student APIs here.",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# The bearer middleware is outermost (last added) and rejects from headers
# before FastAPI or the body limiter receives a single request-body chunk.
app.add_middleware(RequestBodyLimitMiddleware, max_body_size=settings.WORKER_MAX_REQUEST_BODY_BYTES)
app.add_middleware(
    BearerPathAuthMiddleware,
    path_prefix="/internal/worker/",
    secret=lambda: settings.CHT_WORKER_SECRET,
)


class TTSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TTS_INPUT_CHARS)
    profile: SpeechProfile


class TTSResponse(BaseModel):
    audio_base64: str


class AudioProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_base64: str = Field(min_length=1, max_length=settings.WORKER_MAX_AUDIO_BASE64_CHARS)
    filename: str = Field(default="audio.webm", max_length=255)


class AudioProcessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mp3_base64: str
    transcript: str = Field(max_length=12_000)
    metrics: dict | None = None


def require_worker_secret(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker token required")
    if not settings.CHT_WORKER_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Worker secret is not configured")
    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, settings.CHT_WORKER_SECRET):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker token")


@app.head("/healthz", include_in_schema=False)
@app.get("/healthz", include_in_schema=False)
async def public_health() -> Response:
    return Response(status_code=status.HTTP_200_OK)


@app.get("/internal/worker/health", dependencies=[Depends(require_worker_secret)])
async def health() -> dict:
    return {"ok": True}


@app.post("/internal/worker/tts", response_model=TTSResponse, dependencies=[Depends(require_worker_secret)])
async def worker_tts(payload: TTSRequest) -> TTSResponse:
    audio = await generate_speech_local(payload.text, payload.profile)
    return TTSResponse(audio_base64=base64.b64encode(audio).decode("ascii"))


@app.post(
    "/internal/worker/audio/process",
    response_model=AudioProcessResponse,
    dependencies=[Depends(require_worker_secret)],
)
async def worker_audio_process(payload: AudioProcessRequest) -> AudioProcessResponse:
    from app.services import whisper
    from app.services.audio_processor import validate_canonical_mp3

    try:
        audio_bytes = base64.b64decode(payload.audio_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid audio_base64") from exc

    # The internal protocol accepts only the canonical MP3 produced by the web
    # service.  Revalidate independently; accepting and re-encoding arbitrary
    # raw containers here would weaken that protocol and add a lossy pass.
    await validate_canonical_mp3(audio_bytes)
    mp3_bytes = audio_bytes
    transcript, metrics = await whisper.transcribe_with_metrics(
        mp3_bytes,
        "audio.mp3",
    )
    return AudioProcessResponse(
        mp3_base64=base64.b64encode(mp3_bytes).decode("ascii"),
        transcript=transcript,
        metrics=metrics,
    )
