"""Output helpers."""

from __future__ import annotations

import json
import sys
from typing import Any

from linkwarden_cli.errors import InputError


def emit_json(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def emit_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("(none)")
        return
    widths = [len(item) for item in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    fmt = "  ".join(f"{{:<{width}}}" for width in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * width for width in widths]))
    for row in rows:
        print(fmt.format(*row))


def emit(data: Any, *, use_json: bool, text_fn: Any | None = None) -> None:
    if use_json or text_fn is None:
        emit_json(data)
        return
    text_fn(data)


def read_json_input(path: str) -> Any:
    try:
        if path == "-":
            return json.load(sys.stdin)
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None
    except json.JSONDecodeError as exc:
        source = "stdin" if path == "-" else path
        raise InputError(f"invalid JSON in {source}: {exc}") from None


def response_data(data: Any) -> Any:
    if isinstance(data, dict):
        if "response" in data:
            return data["response"]
        if isinstance(data.get("data"), dict) and "links" in data["data"]:
            return data["data"]
        if "data" in data:
            return data["data"]
    return data


def short(value: Any, default: str = "-") -> str:
    if value is None or value == "":
        return default
    return str(value)


def yn(value: Any) -> str:
    return "yes" if value else "no"


def truncate(value: Any, limit: int = 80) -> str:
    text = short(value, "")
    return text if len(text) <= limit else f"{text[: limit - 3]}..."
