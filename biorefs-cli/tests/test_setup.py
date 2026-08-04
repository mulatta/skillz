# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from biorefs_cli.config import default_config_path, load_config
from biorefs_cli.main import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_setup_writes_config_without_secret_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"

    status = main(
        [
            "setup",
            "--email",
            "user@example.org",
            "--ncbi-api-key-command",
            "secret-tool lookup ncbi key",
            "--semantic-scholar-api-key-command",
            "secret-tool lookup s2 key",
            "--timeout-seconds",
            "7",
            "--config",
            str(config_path),
        ],
    )

    assert status == 0
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data == {
        "email": "user@example.org",
        "ncbi_api_key_command": "secret-tool lookup ncbi key",
        "semantic_scholar_api_key_command": "secret-tool lookup s2 key",
        "timeout_seconds": 7,
    }
    assert "api_key" not in data


def test_setup_check_requires_existing_config_without_updates(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "missing.json"

    status = main(["setup", "--config", str(config_path), "--check"])

    captured = capsys.readouterr()
    assert status == 1
    assert "config file not found" in captured.err


def test_setup_check_runs_secret_commands_without_printing_stdout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {"ncbi_api_key_command": "printf 'TOPSECRET\\n'", "timeout_seconds": 3},
        ),
        encoding="utf-8",
    )

    status = main(["setup", "--config", str(config_path), "--check"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert status == 0
    assert payload["config_path"] == str(config_path)
    assert "TOPSECRET" not in captured.out
    assert "TOPSECRET" not in captured.err
    assert "ncbi_api_key_command" in captured.out


def test_setup_check_with_updates_writes_then_validates(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.json"

    status = main(
        [
            "setup",
            "--config",
            str(config_path),
            "--email",
            "user@example.org",
            "--ncbi-api-key-command",
            "printf shell-secret | tr a-z A-Z",
            "--check",
        ],
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "SHELL-SECRET" not in captured.out
    payload = json.loads(captured.out)
    assert payload["config_path"] == str(config_path)
    assert payload["checked"] == ["ncbi_api_key_command"]
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["ncbi_api_key_command"] == "printf shell-secret | tr a-z A-Z"


def test_secret_command_output_never_leaks_on_check_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = write_script(
        tmp_path / "failing-command",
        "#!/bin/sh\nprintf 'STDOUTSECRET\\n'\nprintf 'STDERRSECRET\\n' >&2\nexit 1\n",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"ncbi_api_key_command": str(command), "timeout_seconds": 3}),
        encoding="utf-8",
    )

    status = main(["setup", "--config", str(config_path), "--check"])

    captured = capsys.readouterr()
    assert status == 1
    assert "STDOUTSECRET" not in captured.out
    assert "STDOUTSECRET" not in captured.err
    assert "STDERRSECRET" not in captured.out
    assert "STDERRSECRET" not in captured.err
    assert "credential command failed" in captured.err


def test_default_config_path_uses_xdg_config_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert default_config_path() == tmp_path / "biorefs-cli" / "config.json"


def test_load_missing_config_returns_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.json")

    assert config.email is None
    assert config.timeout_seconds == 30


def write_script(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path
