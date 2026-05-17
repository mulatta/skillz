from __future__ import annotations

import json
from pathlib import Path

import pytest

from miniflux_cli.main import main


def test_setup_writes_config_and_checks_token_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"

    result = main(
        [
            "--config",
            str(config),
            "setup",
            "--api-url",
            "https://miniflux.example.com/",
            "--token-command",
            "printf test-token",
        ]
    )

    assert result == 0
    data = json.loads(config.read_text())
    assert data == {
        "api_url": "https://miniflux.example.com",
        "token_command": "printf test-token",
    }
    out = capsys.readouterr().out
    assert f"Wrote {config}" in out
    assert "Token command works" in out
    assert "test-token" not in out
