"""Shared audio handling for student recording endpoints: upload validation,
transcoding to mp3, object-storage upload, and transcription with fluency metrics."""
import asyncio
import logging
import math

from fastapi import HTTPException, UploadFile

from app.config import settings
from app.services import storage, whisper, worker_client

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 50 * 1024 * 1024  # 50 MB
_audio_processing_semaphore = asyncio.Semaphore(settings.AUDIO_PROCESSING_MAX_CONCURRENCY)

# Accepted audio magic bytes: WebM, Ogg, MP3 (ID3 / sync), WAV
_AUDIO_MAGIC = (
    b'\x1a\x45\xdf\xa3',  # WebM / MKV (Matroska)
    b'OggS',               # Ogg (Opus/Vorbis)
    b'ID3',                # MP3 with ID3 tag
    b'RIFF',               # WAV (RIFF header)
)
_SYNC_BYTES = {b'\xff\xfb', b'\xff\xf3', b'\xff\xf2', b'\xff\xe3'}  # raw MP3 sync


def audio_filename_for_content(data: bytes, key_stem: str) -> str:
    """Return a filename whose extension matches the validated audio bytes."""
    if data.startswith(b'\x1a\x45\xdf\xa3'):
        extension = "webm"
    elif data.startswith(b'OggS'):
        extension = "ogg"
    elif data.startswith(b'RIFF'):
        extension = "wav"
    elif data.startswith(b'ID3') or data[:2] in _SYNC_BYTES:
        extension = "mp3"
    elif data[4:8] == b'ftyp':
        extension = "m4a"
    else:
        extension = "audio"
    return f"{key_stem}.{extension}"


def validate_audio_upload(data: bytes) -> None:
    """Reject oversized files and content whose magic bytes are not a supported audio format."""
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail=f"音訊檔案過大，上限為 {MAX_AUDIO_BYTES // 1024 // 1024} MB。")
    if len(data) < 8:
        raise HTTPException(status_code=400, detail="上傳的音訊檔案無效。")
    if any(data.startswith(m) for m in _AUDIO_MAGIC):
        return
    if data[:2] in _SYNC_BYTES:
        return
    # MP4/M4A: bytes 4-7 must be the 'ftyp' box type identifier
    if data[4:8] == b'ftyp':
        return
    raise HTTPException(status_code=400, detail="不支援的音訊格式，請上傳 WebM、MP3 或 Ogg 格式的音訊。")


async def validate_audio_duration(data: bytes) -> float:
    """Probe a validated upload and reject unknown or over-limit duration.

    This runs before worker routing or transcription so a small, very long audio
    file cannot consume unbounded ffmpeg/OpenAI work. The worker calls it again
    because its bearer API is an independent trust boundary.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        "pipe:0",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _stderr = await asyncio.wait_for(proc.communicate(input=data), timeout=10.0)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.communicate()
        raise HTTPException(status_code=400, detail="無法確認音訊長度，請重新錄製後再試。") from exc
    try:
        duration = float(stdout.decode("ascii", errors="strict").strip())
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="無法確認音訊長度，請重新錄製後再試。") from exc
    if proc.returncode != 0 or not math.isfinite(duration) or duration <= 0:
        raise HTTPException(status_code=400, detail="無法確認音訊長度，請重新錄製後再試。")
    if duration > settings.MAX_AUDIO_SECONDS + 1.0:
        raise HTTPException(
            status_code=400,
            detail=f"錄音最長為 {settings.MAX_AUDIO_SECONDS // 60} 分鐘，請縮短後再上傳。",
        )
    return duration


async def read_audio_checked(audio: UploadFile) -> bytes:
    """Read an upload, rejecting early on Content-Length and capping the read size."""
    content_length = audio.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail=f"音訊檔案過大，上限為 {MAX_AUDIO_BYTES // 1024 // 1024} MB。")
        except ValueError:
            pass
    return await audio.read(MAX_AUDIO_BYTES + 1)


async def process_audio_upload(
    audio: UploadFile,
    student_id: str,
    submission_id: int,
    key_stem: str,
) -> tuple[str, str, dict | None]:
    """Validate, transcode to mp3, upload to storage, and transcribe a recording.

    Returns (audio_key, transcript, metrics). `key_stem` names the object under
    audio/{student_id}/{submission_id}/{key_stem}.mp3.
    """
    audio_bytes = await read_audio_checked(audio)
    validate_audio_upload(audio_bytes)
    await validate_audio_duration(audio_bytes)
    source_filename = audio_filename_for_content(audio_bytes, key_stem)
    worker_result = await worker_client.process_audio(audio_bytes, source_filename)
    if worker_result is not None:
        mp3_bytes, transcript, metrics = worker_result
        audio_key = f"audio/{student_id}/{submission_id}/{key_stem}.mp3"
        await storage.upload_file_async(audio_key, mp3_bytes, "audio/mpeg")
        return audio_key, transcript, metrics

    async with _audio_processing_semaphore:
        (mp3_bytes, (transcript, metrics)) = await asyncio.gather(
            storage.convert_webm_to_mp3(audio_bytes),
            whisper.transcribe_with_metrics(audio_bytes, source_filename),
        )
        audio_key = f"audio/{student_id}/{submission_id}/{key_stem}.mp3"
        await storage.upload_file_async(audio_key, mp3_bytes, "audio/mpeg")
    return audio_key, transcript, metrics
