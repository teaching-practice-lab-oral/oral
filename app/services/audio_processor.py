"""Shared, fail-closed audio validation and processing for student recordings.

Raw browser uploads are an untrusted container boundary.  They must be fully
probed and decoded into the one canonical format used by the rest of the
application before they can reach a worker, transcription provider, or object
storage.
"""
import asyncio
import concurrent.futures
import json
import logging
import math
import subprocess
import tempfile
import io
import zipfile
from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from app.config import settings
from app.services import storage, whisper, worker_client

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 50 * 1024 * 1024  # 50 MiB, raw upload
MAX_NORMALIZED_AUDIO_BYTES = 5 * 1024 * 1024
MAX_TRANSCRIPT_CHARS = 12_000
_FFPROBE_TIMEOUT_SECONDS = 10.0
_FFMPEG_TIMEOUT_SECONDS = 60.0
_MAX_PROBE_OUTPUT_BYTES = 64 * 1024
_audio_processing_semaphore = asyncio.Semaphore(settings.AUDIO_PROCESSING_MAX_CONCURRENCY)
_audio_normalization_semaphore = asyncio.Semaphore(2)
_audio_probe_semaphore = asyncio.Semaphore(4)
_audio_subprocess_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="audio-media",
)

_SYNC_BYTES = {b'\xff\xfb', b'\xff\xf3', b'\xff\xf2', b'\xff\xe3'}
_MP4_FORMAT_NAMES = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}
_GENERIC_AUDIO_MIME_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
_MIME_TYPES_BY_FAMILY = {
    "wav": {"audio/wav", "audio/wave", "audio/x-wav", "audio/vnd.wave"},
    "mp3": {"audio/mpeg", "audio/mp3", "audio/x-mp3"},
    "ogg": {"audio/ogg", "application/ogg"},
    "webm": {"audio/webm", "video/webm"},
    # Safari may label an audio-only MediaRecorder result as video/mp4.
    "mp4": {"audio/mp4", "audio/m4a", "audio/x-m4a", "video/mp4", "application/mp4"},
}


@dataclass(frozen=True)
class AudioProbe:
    family: str
    format_name: str
    codec_name: str
    duration_seconds: float
    channels: int
    sample_rate: int


@dataclass(frozen=True)
class PreparedAudioUpload:
    """A fully decoded, canonical MP3 that is safe for downstream services."""

    data: bytes
    source_filename: str
    key_stem: str


def _invalid_audio(detail: str = "上傳的音訊檔案無效，請重新錄製後再試。") -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def _magic_family(data: bytes) -> str | None:
    if data.startswith(b'\x1a\x45\xdf\xa3'):
        return "webm"
    if data.startswith(b'OggS'):
        return "ogg"
    if data.startswith(b'RIFF') and len(data) >= 12 and data[8:12] == b'WAVE':
        return "wav"
    if data.startswith(b'ID3') or data[:2] in _SYNC_BYTES:
        return "mp3"
    if len(data) >= 12 and data[4:8] == b'ftyp':
        return "mp4"
    return None


def audio_filename_for_content(data: bytes, key_stem: str) -> str:
    """Return a filename based only on inspected bytes, never a client filename."""
    extension = {
        "webm": "webm",
        "ogg": "ogg",
        "wav": "wav",
        "mp3": "mp3",
        "mp4": "m4a",
    }.get(_magic_family(data), "audio")
    return f"{key_stem}.{extension}"


def validate_audio_upload(data: bytes) -> None:
    """Apply cheap size and signature checks before starting ffprobe."""
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"音訊檔案過大，上限為 {MAX_AUDIO_BYTES // 1024 // 1024} MB。",
        )
    family = _magic_family(data)
    if len(data) < 12 or family is None:
        raise _invalid_audio(
            "不支援或無效的音訊格式，請上傳 WAV、MP3、Ogg、WebM 或 M4A 音訊。"
        )
    if family == "wav" and int.from_bytes(data[4:8], "little") + 8 != len(data):
        raise _invalid_audio("WAV 容器長度與實際檔案不一致。")
    # Python's ZIP parser deliberately recognizes self-extracting archives
    # with an arbitrary prefix.  Therefore a payload accepted here would be a
    # genuine audio/ZIP polyglot, even if ffmpeg silently ignored its suffix.
    if zipfile.is_zipfile(io.BytesIO(data)):
        raise _invalid_audio("音訊不可同時包含壓縮封存內容。")


def _positive_finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


async def _run_subprocess_job(function, data: bytes):
    """Run bounded media work off-loop and remain portable across loop policies.

    Polling the future avoids coupling subprocess completion to the event loop's
    child-watcher implementation.  The subprocess functions have their own
    hard timeouts, so cancellation cannot leave unbounded work behind.
    """
    future = _audio_subprocess_executor.submit(function, data)
    try:
        while not future.done():
            await asyncio.sleep(0.01)
        return future.result()
    except asyncio.CancelledError:
        future.cancel()
        raise


def _validated_probe_payload(data: bytes, payload: object) -> AudioProbe:
    if not isinstance(payload, dict):
        raise _invalid_audio()
    streams = payload.get("streams")
    format_data = payload.get("format")
    if not isinstance(streams, list) or len(streams) != 1 or not isinstance(format_data, dict):
        raise _invalid_audio("音訊必須只包含一條音軌，且不得包含影片或其他資料流。")

    stream = streams[0]
    if not isinstance(stream, dict) or stream.get("codec_type") != "audio":
        raise _invalid_audio("檔案內沒有可使用的音軌，或同時包含非音訊資料流。")

    try:
        channels = int(stream.get("channels"))
        sample_rate = int(stream.get("sample_rate"))
    except (TypeError, ValueError) as exc:
        raise _invalid_audio("無法確認音訊聲道或取樣率。") from exc
    if channels not in {1, 2}:
        raise _invalid_audio("音訊僅支援單聲道或雙聲道。")
    if not 8_000 <= sample_rate <= 96_000:
        raise _invalid_audio("音訊取樣率必須介於 8 kHz 與 96 kHz。")

    magic_family = _magic_family(data)
    format_names = {
        item.strip().lower()
        for item in str(format_data.get("format_name") or "").split(",")
        if item.strip()
    }
    codec_name = str(stream.get("codec_name") or "").strip().lower()
    valid_family = (
        magic_family == "wav" and "wav" in format_names and codec_name.startswith("pcm_")
        or magic_family == "mp3" and "mp3" in format_names and codec_name == "mp3"
        or magic_family == "ogg" and "ogg" in format_names and codec_name in {"opus", "vorbis"}
        or magic_family == "webm"
        and bool(format_names & {"matroska", "webm"})
        and codec_name in {"opus", "vorbis"}
        or magic_family == "mp4"
        and bool(format_names & _MP4_FORMAT_NAMES)
        and codec_name in {"aac", "alac"}
    )
    if not valid_family or magic_family is None:
        raise _invalid_audio("音訊容器與編碼不相符，或使用了不支援的編碼。")

    duration = _positive_finite_float(format_data.get("duration"))
    if duration is None:
        duration = _positive_finite_float(stream.get("duration"))
    if duration is None:
        raise _invalid_audio("無法確認音訊長度，請重新錄製後再試。")
    if duration > settings.MAX_AUDIO_SECONDS + 1.0:
        raise _invalid_audio(
            f"錄音最長為 {settings.MAX_AUDIO_SECONDS // 60} 分鐘，請縮短後再上傳。"
        )
    return AudioProbe(
        family=magic_family,
        format_name=",".join(sorted(format_names)),
        codec_name=codec_name,
        duration_seconds=duration,
        channels=channels,
        sample_rate=sample_rate,
    )


def _validate_content_type(content_type: str | None, family: str) -> None:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized in _GENERIC_AUDIO_MIME_TYPES:
        return
    if normalized not in _MIME_TYPES_BY_FAMILY[family]:
        raise _invalid_audio("上傳的媒體類型與實際音訊格式不相符。")


def _probe_audio_sync(data: bytes) -> object:
    try:
        suffix = f".{_magic_family(data) or 'audio'}"
        with tempfile.NamedTemporaryFile(suffix=suffix) as source_file:
            source_file.write(data)
            source_file.flush()
            result = subprocess.run(
                [
                "ffprobe",
                "-v", "error",
                "-probesize", "8388608",
                "-analyzeduration", "10000000",
                "-show_entries",
                "format=format_name,duration:stream=index,codec_type,codec_name,channels,sample_rate,duration",
                "-of", "json",
                source_file.name,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=_FFPROBE_TIMEOUT_SECONDS,
                check=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise _invalid_audio("音訊驗證逾時，請重新錄製後再試。") from exc
    except FileNotFoundError as exc:
        logger.exception("ffprobe is unavailable")
        raise HTTPException(status_code=503, detail="音訊驗證服務暫時無法使用。") from exc

    if result.returncode != 0 or len(result.stdout) > _MAX_PROBE_OUTPUT_BYTES:
        raise _invalid_audio()
    try:
        return json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid_audio() from exc


async def probe_audio(data: bytes, *, content_type: str | None = None) -> AudioProbe:
    """Return a strict ffprobe description of one supported audio-only stream."""
    validate_audio_upload(data)
    async with _audio_probe_semaphore:
        payload = await _run_subprocess_job(_probe_audio_sync, data)
    probe = _validated_probe_payload(data, payload)
    _validate_content_type(content_type, probe.family)
    return probe


async def validate_audio_duration(data: bytes) -> float:
    """Compatibility wrapper that now performs complete structural probing."""
    return (await probe_audio(data)).duration_seconds


def _normalize_with_ffmpeg_sync(data: bytes) -> bytes:
    try:
        with (
            tempfile.NamedTemporaryFile(
                suffix=f".{_magic_family(data) or 'audio'}"
            ) as source_file,
            tempfile.TemporaryFile() as output_file,
            tempfile.TemporaryFile() as error_file,
        ):
            source_file.write(data)
            source_file.flush()
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel", "error",
                    "-threads", "1",
                    # Decoders commonly conceal corrupt frames and still exit
                    # zero.  Security validation requires a complete clean
                    # decode, so promote every decode warning/error to failure.
                    "-xerror",
                    "-i", source_file.name,
                    "-map", "0:a:0",
                    "-vn", "-sn", "-dn",
                    "-map_metadata", "-1",
                    "-ac", "1",
                    "-ar", "48000",
                    "-codec:a", "libmp3lame",
                    "-b:a", "96k",
                    "-id3v2_version", "0",
                    "-write_id3v1", "0",
                    "-f", "mp3",
                    "pipe:1",
                ],
                stdout=output_file,
                stderr=error_file,
                timeout=_FFMPEG_TIMEOUT_SECONDS,
                check=False,
            )
            error_file.seek(0)
            error_text = error_file.read(4096).decode("utf-8", errors="replace")
            if result.returncode != 0:
                logger.info("Rejected undecodable audio: %s", error_text[:512])
                raise _invalid_audio("音訊無法完整解碼，請重新錄製後再試。")
            output_file.seek(0, 2)
            output_size = output_file.tell()
            if output_size <= 0 or output_size > MAX_NORMALIZED_AUDIO_BYTES:
                raise _invalid_audio("正規化後的音訊大小無效。")
            output_file.seek(0)
            return output_file.read()
    except subprocess.TimeoutExpired as exc:
        raise _invalid_audio("音訊轉換逾時，請縮短錄音後再試。") from exc
    except FileNotFoundError as exc:
        logger.exception("ffmpeg is unavailable")
        raise HTTPException(status_code=503, detail="音訊轉換服務暫時無法使用。") from exc


async def _normalize_with_ffmpeg(data: bytes) -> bytes:
    async with _audio_normalization_semaphore:
        return await _run_subprocess_job(_normalize_with_ffmpeg_sync, data)


async def validate_canonical_mp3(data: bytes) -> AudioProbe:
    """Validate the only audio representation trusted by downstream systems."""
    if len(data) > MAX_NORMALIZED_AUDIO_BYTES:
        raise _invalid_audio("正規化音訊超過允許大小。")
    probe = await probe_audio(data, content_type="audio/mpeg")
    if (
        probe.family != "mp3"
        or probe.codec_name != "mp3"
        or probe.channels != 1
        or probe.sample_rate != 48_000
    ):
        raise _invalid_audio("音訊未符合安全的正規化格式。")
    return probe


async def normalize_audio(data: bytes, *, content_type: str | None = None) -> tuple[bytes, AudioProbe]:
    """Fully decode one supported audio-only input into canonical MP3."""
    source_probe = await probe_audio(data, content_type=content_type)
    mp3_bytes = await _normalize_with_ffmpeg(data)
    canonical_probe = await validate_canonical_mp3(mp3_bytes)
    # A corrupt or adversarial conversion must not manufacture a longer file.
    if canonical_probe.duration_seconds > source_probe.duration_seconds + 1.0:
        raise _invalid_audio("正規化後的音訊長度與原始錄音不相符。")
    return mp3_bytes, canonical_probe


async def read_audio_checked(audio: UploadFile) -> bytes:
    """Read an upload, rejecting early on Content-Length and capping the read size."""
    content_length = audio.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_AUDIO_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"音訊檔案過大，上限為 {MAX_AUDIO_BYTES // 1024 // 1024} MB。",
                )
        except ValueError:
            pass
    return await audio.read(MAX_AUDIO_BYTES + 1)


async def prepare_audio_upload(audio: UploadFile, key_stem: str) -> PreparedAudioUpload:
    """Validate and normalize before any external API allowance is consumed."""
    audio_bytes = await read_audio_checked(audio)
    canonical_mp3, _probe = await normalize_audio(
        audio_bytes,
        content_type=audio.content_type,
    )
    return PreparedAudioUpload(
        data=canonical_mp3,
        source_filename=f"{key_stem}.mp3",
        key_stem=key_stem,
    )


async def transcribe_prepared_audio(
    prepared: PreparedAudioUpload,
) -> tuple[bytes, str, dict | None]:
    """Transcribe canonical MP3 without creating an object-storage side effect."""
    canonical_mp3 = prepared.data
    await validate_canonical_mp3(canonical_mp3)
    worker_result = await worker_client.process_audio(canonical_mp3, prepared.source_filename)
    if worker_result is not None:
        mp3_bytes, transcript, metrics = worker_result
    else:
        async with _audio_processing_semaphore:
            transcript, metrics = await whisper.transcribe_with_metrics(
                canonical_mp3, prepared.source_filename
            )
        mp3_bytes = canonical_mp3

    if len(transcript) > MAX_TRANSCRIPT_CHARS or "\x00" in transcript:
        raise _invalid_audio("語音辨識結果無效，請重新錄製後再試。")
    return mp3_bytes, transcript, metrics


async def store_processed_audio(
    mp3_bytes: bytes,
    student_id: str,
    submission_id: int,
    key_stem: str,
) -> str:
    """Validate and store one accepted canonical recording."""
    await validate_canonical_mp3(mp3_bytes)
    audio_key = storage.object_key(
        "audio",
        student_id,
        submission_id,
        f"{key_stem}_{uuid4().hex}.mp3",
    )
    await storage.upload_file_async(audio_key, mp3_bytes, "audio/mpeg")
    return audio_key


async def process_prepared_audio(
    prepared: PreparedAudioUpload,
    student_id: str,
    submission_id: int,
) -> tuple[str, str, dict | None]:
    """Transcribe and store canonical MP3 for flows without a post-STT gate."""
    mp3_bytes, transcript, metrics = await transcribe_prepared_audio(prepared)
    audio_key = await store_processed_audio(
        mp3_bytes,
        student_id,
        submission_id,
        prepared.key_stem,
    )
    return audio_key, transcript, metrics
