from __future__ import annotations

import json
from pathlib import Path

import pytest

from vikunja_cli.config import resolve_credentials, write_config


def test_write_config_stores_command_not_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.json"
    path = write_config("https://vikunja.example.com/", "printf token", str(config))

    assert path == config
    data = json.loads(config.read_text())
    assert data == {
        "base_url": "https://vikunja.example.com",
        "api_key_command": "printf token",
    }


def test_resolve_credentials_prefers_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "base_url": "https://config.example.com",
                "api_key_command": "printf config-token",
            }
        )
    )
    monkeypatch.setenv("VIKUNJA_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("VIKUNJA_API_KEY", "env-token")

    assert resolve_credentials(str(config)) == ("https://env.example.com", "env-token", 30)


def test_resolve_credentials_runs_api_key_command_without_shell(tmp_path: Path) -> None:
    script = tmp_path / "print-token"
    script.write_text("#!/bin/sh\nprintf '%s\\n' token-from-command\n")
    script.chmod(0o755)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "base_url": "https://vikunja.example.com",
                "api_key_command": str(script),
            }
        )
    )

    assert resolve_credentials(str(config)) == (
        "https://vikunja.example.com",
        "token-from-command",
        30,
    )
