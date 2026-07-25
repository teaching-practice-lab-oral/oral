"""Unauthenticated bearer-token downloads for expiring result packages."""

import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import ResultPackage
from app.services import storage
from app.services.result_delivery import result_download_token_hash
from app.utils import taipei_now


router = APIRouter(tags=["result-downloads"])
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


@router.get("/downloads/results/{token}", include_in_schema=False)
def download_result_package(
    token: str,
    db: Session = Depends(get_db),
):
    if not _TOKEN_PATTERN.fullmatch(token):
        raise HTTPException(status_code=404, detail="下載連結不存在")
    package = (
        db.query(ResultPackage)
        .filter(ResultPackage.token_hash == result_download_token_hash(token))
        .first()
    )
    if package is None:
        raise HTTPException(status_code=404, detail="下載連結不存在")
    if (
        not package.object_key
        or not storage.is_current_object_key(package.object_key, "result-packages")
        or not package.expires_at
        or package.expires_at <= taipei_now()
        or package.state == "expired"
    ):
        raise HTTPException(status_code=410, detail="下載連結已過期")
    try:
        if not storage.object_exists(package.object_key):
            package.state = "expired"
            db.commit()
            raise HTTPException(status_code=410, detail="成果包已不存在")
        url = storage.generate_presigned_url(
            package.object_key,
            expiration=settings.RESULT_DOWNLOAD_REDIRECT_SECONDS,
            download_filename=package.filename,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="暫時無法建立下載連結") from exc
    return RedirectResponse(
        url=url,
        status_code=302,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )
