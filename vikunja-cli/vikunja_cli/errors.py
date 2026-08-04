# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""User-facing errors for vikunja-cli."""

from http import HTTPStatus

_HINTS: dict[int, str] = {
    400: "check command arguments",
    401: "check API token",
    403: "insufficient API token permissions",
    404: "object not found or not visible with current permissions",
}


class CLIError(Exception):
    """Base class for errors shown without a traceback."""


class ConfigError(CLIError):
    """Missing or invalid configuration."""


class InputError(CLIError):
    """Invalid user input."""


class APIError(CLIError):
    """HTTP error returned by Vikunja."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        try:
            phrase = HTTPStatus(status).phrase
        except ValueError:
            phrase = f"HTTP {status}"
        hint = _HINTS.get(status)
        label = f"{phrase} ({hint})" if hint else phrase
        super().__init__(f"{label}: {message}" if message else label)


class ConnectionError_(CLIError):
    """Network error while contacting Vikunja."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Cannot connect to Vikunja: {reason}")
