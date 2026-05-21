"""Output helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def markdown_heading(title: str, *, level: int = 1) -> str:
    return f"{'#' * level} {title}"


def markdown_table(headers: Iterable[str], rows: Iterable[Iterable[object]]) -> str:
    header_list = list(headers)
    lines = [
        "| " + " | ".join(header_list) + " |",
        "| " + " | ".join("---" for _item in header_list) + " |",
    ]
    lines.extend(
        "| " + " | ".join(escape_cell(str(value)) for value in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
