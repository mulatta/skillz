# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""User-facing errors."""

from __future__ import annotations

from http import HTTPStatus


class CLIError(Exception):
    """Base error shown without traceback."""


class ConfigError(CLIError):
    """Configuration is missing or invalid."""


class InputError(CLIError):
    """User input is invalid."""


class APIError(CLIError):
    """The zhost server returned an error response."""

    def __init__(self, status: int, message: str) -> None:
        try:
            phrase = HTTPStatus(status).phrase
        except ValueError:
            phrase = f"HTTP {status}"
        super().__init__(f"{phrase}: {message}" if message else phrase)
        self.status = status


class ConflictError(APIError):
    """A version precondition failed (HTTP 412); the library moved on.

    Carries the server's current library version so a caller can re-read and
    retry the write against the fresh version.
    """

    def __init__(self, current_version: int | None, message: str) -> None:
        super().__init__(HTTPStatus.PRECONDITION_FAILED, message)
        self.current_version = current_version


class ConnectionError_(CLIError):
    """The zhost server could not be reached."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Cannot connect to zhost: {reason}")
