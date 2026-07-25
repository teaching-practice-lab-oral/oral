import asyncio
import re
from urllib.parse import quote

from botocore.exceptions import ClientError

from app.config import settings


async def convert_webm_to_mp3(webm_bytes: bytes) -> bytes:
    """Convert webm audio bytes to mp3 using ffmpeg."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", "pipe:0", "-f", "mp3", "-q:a", "2", "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=webm_bytes), timeout=60.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("ffmpeg conversion timed out after 60 seconds")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {stderr.decode()}")
    return stdout

_s3_client = None
_NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")


def current_namespace() -> str:
    namespace = settings.OBJECT_STORAGE_NAMESPACE.strip()
    if not _NAMESPACE_PATTERN.fullmatch(namespace):
        raise RuntimeError("OBJECT_STORAGE_NAMESPACE is missing or invalid")
    return namespace


def object_key(category: str, *parts: object) -> str:
    """Build a key owned by this database generation."""
    if category not in {"audio", "reflection", "result-packages"}:
        raise ValueError("unsupported object-storage category")
    clean_parts = []
    for part in parts:
        value = str(part).strip("/")
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("invalid object-key component")
        clean_parts.append(value)
    return "/".join((current_namespace(), category, *clean_parts))


def object_prefix(category: str, *parts: object) -> str:
    return object_key(category, *parts) + "/"


def is_current_object_key(key: str, category: str) -> bool:
    try:
        prefix = f"{current_namespace()}/{category}/"
    except RuntimeError:
        return False
    return bool(key) and key.startswith(prefix)


def is_current_owned_key(key: str) -> bool:
    return any(
        is_current_object_key(key, category)
        for category in ("audio", "reflection", "result-packages")
    )


def _require_current_owned_key(key: str) -> None:
    if not is_current_owned_key(key):
        raise ValueError("object key is outside OBJECT_STORAGE_NAMESPACE")


def _get_client():
    global _s3_client
    if _s3_client is None:
        # Keep the optional storage SDK out of app/test import paths until an
        # object operation is actually requested.
        import boto3

        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.OCI_ENDPOINT_URL,
            aws_access_key_id=settings.OCI_ACCESS_KEY_ID,
            aws_secret_access_key=settings.OCI_SECRET_ACCESS_KEY,
            region_name=settings.OCI_REGION,
        )
    return _s3_client


def upload_file(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """
    Upload bytes to OCI Object Storage.
    Returns the object key.
    """
    _require_current_owned_key(key)
    client = _get_client()
    client.put_object(
        Bucket=settings.OCI_BUCKET_NAME,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key


def get_file_url(key: str) -> str:
    """
    Return the direct public URL for an object (if bucket is public).
    """
    _require_current_owned_key(key)
    endpoint = settings.OCI_ENDPOINT_URL.rstrip("/")
    return f"{endpoint}/{settings.OCI_BUCKET_NAME}/{key}"


def generate_presigned_url(
    key: str,
    expiration: int = 300,
    *,
    download_filename: str | None = None,
) -> str:
    """
    Generate a pre-signed URL for temporary access to a private object.
    """
    _require_current_owned_key(key)
    client = _get_client()
    try:
        params = {"Bucket": settings.OCI_BUCKET_NAME, "Key": key}
        if download_filename:
            safe_filename = download_filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
            params["ResponseContentDisposition"] = (
                f"attachment; filename*=UTF-8''{quote(safe_filename)}"
            )
        url = client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expiration,
        )
        return url
    except ClientError as e:
        raise RuntimeError(f"Could not generate presigned URL: {e}") from e


def download_file(key: str) -> bytes:
    """
    Download and return bytes for an object.
    """
    _require_current_owned_key(key)
    client = _get_client()
    response = client.get_object(Bucket=settings.OCI_BUCKET_NAME, Key=key)
    return response["Body"].read()


def object_exists(key: str) -> bool:
    _require_current_owned_key(key)
    try:
        _get_client().head_object(Bucket=settings.OCI_BUCKET_NAME, Key=key)
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def delete_file(key: str) -> None:
    """Delete a private object by key."""
    _require_current_owned_key(key)
    _get_client().delete_object(Bucket=settings.OCI_BUCKET_NAME, Key=key)


def list_objects_with_prefix(prefix: str) -> list:
    """
    List all object keys under a prefix.
    """
    _require_current_owned_key(prefix)
    client = _get_client()
    paginator = client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=settings.OCI_BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


async def upload_file_async(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    return await asyncio.to_thread(upload_file, key, data, content_type)


async def download_file_async(key: str) -> bytes:
    return await asyncio.to_thread(download_file, key)


async def delete_file_async(key: str) -> None:
    await asyncio.to_thread(delete_file, key)


async def generate_presigned_url_async(key: str, expiration: int = 300) -> str:
    return await asyncio.to_thread(generate_presigned_url, key, expiration)


async def list_objects_with_prefix_async(prefix: str) -> list:
    return await asyncio.to_thread(list_objects_with_prefix, prefix)
