from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet


_FORMULA_PREFIXES = {"=", "+", "-", "@", "\t", "\r"}


def append_xlsx_row(
    worksheet: Worksheet,
    values: Iterable[Any],
    *,
    force_text: bool = False,
) -> int:
    """Append a row while keeping externally supplied strings out of formula mode."""
    row_number = worksheet.max_row + 1
    for column, raw_value in enumerate(values, start=1):
        value = "" if raw_value is None else (str(raw_value) if force_text else raw_value)
        cell = worksheet.cell(row=row_number, column=column, value=value)
        if isinstance(value, str) and value[:1] in _FORMULA_PREFIXES:
            cell.data_type = "s"
            cell.quotePrefix = True
    return row_number
