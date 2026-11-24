"""Decode and canonicalize untrusted reflection-photo uploads."""

from __future__ import annotations

import asyncio
import io
import warnings
from dataclasses import dataclass

from fastapi import HTTPException, status


MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_SIDE = 8_192
OUTPUT_MAX_SIDE = 4_096
OUTPUT_CONTENT_TYPE = "image/jpeg"
_processing_slots = asyncio.Semaphore(2)

_FORMAT_MIMES = {
    "JPEG": {"image/jpeg", "image/jpg", "image/pjpeg"},
    "PNG": {"image/png"},
    "WEBP": {"image/webp"},
    "HEIF": {"image/heic", "image/heif", "image/heic-sequence", "image/heif-sequence"},
}


@dataclass(frozen=True)
class NormalizedImage:
    data: bytes
    source_format: str
    width: int
    height: int


def _invalid_photo(detail: str = "照片內容無法驗證，請重新選擇有效的圖片檔案") -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _load_image_modules():
    try:
        from PIL import Image, ImageOps
        from pillow_heif import register_heif_opener
    except ImportError as exc:  # Fail closed if the production image is incomplete.
        raise RuntimeError("Pillow and pillow-heif are required for photo validation") from exc
    register_heif_opener()
    return Image, ImageOps


def normalize_reflection_photo(data: bytes, declared_content_type: str | None) -> NormalizedImage:
    """Fully decode one allowlisted image and return a metadata-free JPEG."""
    if not data:
        raise _invalid_photo("照片檔案不可為空")
    if len(data) > MAX_SOURCE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="照片不可超過 10 MB")

    Image, ImageOps = _load_image_modules()
    declared = (declared_content_type or "").split(";", 1)[0].strip().casefold()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=list(_FORMAT_MIMES)) as probe:
                source_format = str(probe.format or "").upper()
                if source_format not in _FORMAT_MIMES:
                    raise _invalid_photo("照片只接受 JPEG、PNG、WebP、HEIC 或 HEIF")
                if int(getattr(probe, "n_frames", 1)) != 1:
                    raise _invalid_photo("照片不可為動畫或多幀圖片")
                width, height = probe.size
                if width < 1 or height < 1 or width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
                    raise _invalid_photo("照片尺寸過大或像素數不合理")
                probe.verify()

            allowed_mimes = _FORMAT_MIMES[source_format]
            if declared not in {"", "application/octet-stream", "binary/octet-stream"} and declared not in allowed_mimes:
                raise _invalid_photo("照片的 MIME 類型與實際內容不一致")

            with Image.open(io.BytesIO(data), formats=list(_FORMAT_MIMES)) as source:
                if int(getattr(source, "n_frames", 1)) != 1:
                    raise _invalid_photo("照片不可為動畫或多幀圖片")
                source.load()
                oriented = ImageOps.exif_transpose(source)
                oriented.thumbnail((OUTPUT_MAX_SIDE, OUTPUT_MAX_SIDE), Image.Resampling.LANCZOS)
                if oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info:
                    rgba = oriented.convert("RGBA")
                    output_image = Image.new("RGB", rgba.size, "white")
                    output_image.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    output_image = oriented.convert("RGB")
                output = io.BytesIO()
                output_image.save(
                    output,
                    format="JPEG",
                    quality=88,
                    subsampling=2,
                    optimize=True,
                    exif=b"",
                )
                payload = output.getvalue()
                if not payload or len(payload) > MAX_SOURCE_BYTES:
                    raise _invalid_photo("照片正規化後的檔案大小不合理")
                return NormalizedImage(
                    data=payload,
                    source_format=source_format,
                    width=output_image.width,
                    height=output_image.height,
                )
    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise _invalid_photo("照片像素數過大")
    except Exception as exc:
        raise _invalid_photo() from exc


async def normalize_reflection_photo_async(
    data: bytes,
    declared_content_type: str | None,
) -> NormalizedImage:
    async with _processing_slots:
        return await asyncio.to_thread(normalize_reflection_photo, data, declared_content_type)
