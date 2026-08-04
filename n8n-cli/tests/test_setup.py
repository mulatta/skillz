# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from n8n_cli.main import main


def test_setup_writes_config_and_checks_api_key_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"

    with patch(
        "sys.argv",
        [
            "n8n-cli",
            "--config",
            str(config),
            "setup",
            "--api-url",
            "https://n8n.example.com/",
            "--api-key-command",
            "printf test-key",
        ],
    ):
        main()

    data = json.loads(config.read_text())
    assert data == {
        "api_url": "https://n8n.example.com",
        "api_key_command": "printf test-key",
    }
    out = capsys.readouterr().out
    assert f"Wrote {config}" in out
    assert "API key command works" in out
    assert "test-key" not in out
