# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Configuration and API token resolution."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from vikunja_cli.errors import ConfigError

APP_NAME = "vikunja-cli"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_TIMEOUT = 30


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load config JSON, returning empty config when no file exists."""
    path = Path(config_path) if config_path else CONFIG_FILE
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in config file {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"config file {path} must contain a JSON object")
    return loaded


def write_config(
    base_url: str, api_key_command: str, config_path: str | None = None
) -> Path:
    """Write credential config."""
    path = Path(config_path) if config_path else CONFIG_FILE
    command = shlex.split(api_key_command)
    if not command:
        raise ConfigError("api_key_command must not be empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "base_url": base_url.rstrip("/"),
        "api_key_command": api_key_command,
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def run_api_key_command(command: str) -> str | None:
    """Run an api_key_command without invoking a shell."""
    argv = shlex.split(command)
    if not argv:
        return None
    try:
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print(f"Warning: api_key_command timed out: {command}", file=sys.stderr)
        return None
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Warning: api_key_command failed: {exc}", file=sys.stderr)
        return None
    return result.stdout.splitlines()[0].strip() if result.stdout.strip() else None


def _string_value(cfg: dict[str, Any], key: str) -> str | None:
    value = cfg.get(key)
    return value if isinstance(value, str) and value else None


def resolve_credentials(config_path: str | None = None) -> tuple[str, str, int]:
    """Resolve base URL, API token, and timeout.

    Priority: environment variables > config command. Direct tokens in config are
    intentionally unsupported so setup never stores secrets.
    """
    cfg = load_config(config_path)

    base_url = os.environ.get("VIKUNJA_BASE_URL") or _string_value(cfg, "base_url")
    if not base_url:
        raise ConfigError(f"VIKUNJA_BASE_URL not set and {CONFIG_FILE} has no base_url")

    api_key = os.environ.get("VIKUNJA_API_KEY")
    if not api_key:
        command = os.environ.get("VIKUNJA_API_KEY_COMMAND") or _string_value(
            cfg, "api_key_command"
        )
        if command:
            api_key = run_api_key_command(command)
    if not api_key:
        raise ConfigError(
            "VIKUNJA_API_KEY not set and api_key_command did not return a token"
        )

    timeout = DEFAULT_TIMEOUT
    timeout_raw = os.environ.get("VIKUNJA_TIMEOUT") or cfg.get("timeout")
    if timeout_raw is not None:
        try:
            timeout = int(timeout_raw)
        except (TypeError, ValueError):
            raise ConfigError(f"invalid timeout: {timeout_raw!r}") from None
    return base_url, api_key, timeout
