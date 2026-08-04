# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Shared JSON-shape extraction helpers for biorefs-cli command modules.

Command modules parse loosely typed JSON payloads (``dict[str, object]``)
returned by external biomedical APIs. They repeatedly need to pull a value out
of a payload by key while coercing it to a narrow, well-defined shape and
falling back to ``None`` / ``[]`` / ``{}`` when the field is absent or has an
unexpected type.

This module collects the canonical, behaviour-compatible variants of those
helpers so callers can import them instead of redefining identical bodies.

The helpers follow the dominant ``(payload, key)`` accessor convention: each
takes the surrounding object plus the field name and reads ``payload.get(key)``
internally. The variants here use the strictest checks found across callers
(e.g. ``optional_int`` rejects ``bool`` and only parses decimal strings,
``optional_str`` treats empty strings as missing).

Intentionally excluded: ``display`` (lives in :mod:`biorefs_cli.output`) and the
per-source ``provenance`` builders (their shapes differ per module).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast


def optional_str(payload: dict[str, object], key: str) -> str | None:
    """Return ``payload[key]`` if it is a non-empty string, else ``None``."""
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def optional_int(payload: dict[str, object], key: str) -> int | None:
    """Return ``payload[key]`` as ``int`` if it is an int or decimal string.

    ``bool`` values are rejected (a ``bool`` is an ``int`` subclass), and only
    strings consisting solely of decimal digits are parsed.
    """
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def object_or_none(payload: dict[str, object], key: str) -> dict[str, object] | None:
    """Return ``payload[key]`` if it is a dict, else ``None``."""
    value = payload.get(key)
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def object_list(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    """Return the dict items of the list at ``payload[key]``, else ``[]``."""
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def string_list(payload: dict[str, object], key: str) -> list[str]:
    """Return the string items of the list at ``payload[key]``, else ``[]``."""
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def retrieved_at() -> str:
    """Return the current UTC time as a second-precision ISO 8601 string."""
    return datetime.now(UTC).isoformat(timespec="seconds")
