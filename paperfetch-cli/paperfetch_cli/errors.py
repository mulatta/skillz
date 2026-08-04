# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Process exit codes and the user-facing error type.

Exit codes are part of the CLI contract: they let a caller that asked for an
artifact paperfetch could not resolve fall back to ``render`` / ``grab`` using
the manifest's ``candidates``.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_UNRESOLVED = 3
EXIT_FETCH = 4


class CLIError(Exception):
    """A user-facing failure carrying the process exit code to return."""

    def __init__(self, message: str, exit_code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.exit_code = exit_code
