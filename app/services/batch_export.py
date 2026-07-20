"""Shared, explicit partial-failure policy for batch archive exports."""

from dataclasses import dataclass
import io
import logging
from typing import Callable, Iterable, TypeVar
import zipfile

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class BatchExportResult:
    archive: bytes
    attempted: int
    exported: int
    failures: list[str]

    @property
    def partial(self) -> bool:
        return bool(self.failures)


class BatchExportFailed(RuntimeError):
    def __init__(self, failures: list[str]):
        super().__init__("all batch export items failed")
        self.failures = failures


def build_zip_with_manifest(
    items: Iterable[T],
    *,
    render: Callable[[T], tuple[str, bytes]],
    identity: Callable[[T], str],
) -> BatchExportResult:
    """Build a ZIP, recording every omission and refusing a false-success ZIP."""
    rows = list(items)
    failures: list[str] = []
    exported = 0
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in rows:
            item_id = identity(item)
            try:
                filename, payload = render(item)
                archive.writestr(filename, payload)
                exported += 1
            except Exception as exc:
                logger.exception("batch export omitted %s", item_id)
                failures.append(f"{item_id}: {type(exc).__name__}")
        if failures:
            manifest = [
                "此壓縮檔有部分項目匯出失敗。",
                f"嘗試：{len(rows)}；成功：{exported}；失敗：{len(failures)}",
                "",
                *failures,
            ]
            archive.writestr("_匯出失敗清單.txt", "\n".join(manifest).encode("utf-8"))
    if rows and exported == 0:
        raise BatchExportFailed(failures)
    return BatchExportResult(buffer.getvalue(), len(rows), exported, failures)
