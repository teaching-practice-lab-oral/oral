from datetime import datetime
from ipaddress import ip_address, ip_network
from zoneinfo import ZoneInfo

from fastapi import Request

from app.config import settings

PRESIGNED_URL_EXPIRATION = 300


def taipei_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Taipei")).replace(tzinfo=None)


def _parse_ip(value: str | None):
    if not value:
        return None
    try:
        return ip_address(value.strip())
    except ValueError:
        return None


def _is_trusted_proxy(peer_ip: str | None) -> bool:
    if not peer_ip:
        return False
    trusted = settings.trusted_proxy_ips_list
    if "*" in trusted:
        return True
    peer = _parse_ip(peer_ip)
    if peer is None:
        return False
    for raw in trusted:
        try:
            if peer in ip_network(raw, strict=False):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(request: Request | None) -> str | None:
    """Return the caller IP, trusting proxy headers only from configured proxies."""
    if request is None:
        return None
    peer_ip = request.client.host if request.client else None
    if not _is_trusted_proxy(peer_ip):
        return peer_ip

    for header in ("CF-Connecting-IP", "X-Real-IP"):
        parsed = _parse_ip(request.headers.get(header))
        if parsed is not None:
            return str(parsed)

    forwarded_for = request.headers.get("X-Forwarded-For", "")
    for part in forwarded_for.split(","):
        parsed = _parse_ip(part)
        if parsed is not None:
            return str(parsed)
    return peer_ip
