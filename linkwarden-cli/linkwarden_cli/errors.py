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
    """Linkwarden API returned an error."""

    def __init__(self, status: int, message: str) -> None:
        try:
            phrase = HTTPStatus(status).phrase
        except ValueError:
            phrase = f"HTTP {status}"
        super().__init__(f"{phrase}: {message}" if message else phrase)
        self.status = status


class ConnectionError_(CLIError):
    """Linkwarden API could not be reached."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Cannot connect to Linkwarden: {reason}")
