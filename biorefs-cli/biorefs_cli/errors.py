# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Safe CLI errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn


@dataclass(slots=True)
class CLIError(Exception):
    safe_message: str
    exit_code: int = 1

    def __str__(self) -> str:
        return self.safe_message


class ConfigError(CLIError):
    pass


class CredentialCheckError(CLIError):
    pass


class HTTPError(CLIError):
    status: int | None

    def __init__(
        self,
        safe_message: str,
        *,
        status: int | None = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(safe_message, exit_code)
        self.status = status


class RateLimitError(HTTPError):
    retry_after_seconds: float | None

    def __init__(
        self,
        safe_message: str = "rate limited by remote service",
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(safe_message, status=429)
        self.retry_after_seconds = retry_after_seconds


class NotImplementedCommandError(CLIError):
    def __init__(self, command: str, subcommand: str) -> None:
        safe_message = f"{command} {subcommand} is not implemented in scaffold branch"
        super().__init__(safe_message, 2)


def die(message: str, *, exit_code: int = 1) -> NoReturn:
    raise CLIError(message, exit_code)
