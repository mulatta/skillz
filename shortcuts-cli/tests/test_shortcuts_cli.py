# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Tests for shortcuts-cli."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, cast

MODULE_PATH = Path(__file__).parents[1] / "shortcuts_cli.py"
MODULE_SPEC = importlib.util.spec_from_file_location("shortcuts_cli", MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    msg = f"Could not load {MODULE_PATH}"
    raise RuntimeError(msg)
shortcuts_cli = cast("Any", importlib.util.module_from_spec(MODULE_SPEC))
sys.modules["shortcuts_cli"] = shortcuts_cli
MODULE_SPEC.loader.exec_module(shortcuts_cli)


def test_default_output_path_uses_claude_outputs() -> None:
    source = Path("hello.cherri")

    output = shortcuts_cli.default_output_path(source)

    assert output == Path.home() / ".claude" / "outputs" / "hello.shortcut"


def test_unsigned_output_path_matches_cherri_skip_sign_suffix() -> None:
    output = Path("/example/hello.shortcut")

    unsigned = shortcuts_cli.unsigned_output_path(output)

    assert unsigned == Path("/example/hello_unsigned.shortcut")


def test_build_command_uses_signed_output() -> None:
    options = shortcuts_cli.BuildOptions(
        source=Path("hello.cherri"),
        output=Path("/example/hello.shortcut"),
        open_after_build=True,
        comments=True,
    )

    command = shortcuts_cli.build_cherri_command(options)

    assert command == [
        "cherri",
        "hello.cherri",
        "--output=/example/hello.shortcut",
        "--no-ansi",
        "--comments",
    ]


def test_validate_command_skips_signing() -> None:
    command = shortcuts_cli.validate_cherri_command(
        Path("hello.cherri"),
        comments=True,
    )

    assert command == [
        "cherri",
        "hello.cherri",
        "--skip-sign",
        "--no-ansi",
        "--comments",
    ]
