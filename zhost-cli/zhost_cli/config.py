# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Configuration and API-key resolution.

zhost speaks the Zotero Web API v3 sync subset. Auth is a single Bearer-style
key sent in the `Zotero-API-Key` header, provisioned out of band (see the zhost
SPEC; never minted by this CLI). The library is addressed as `/users/<user_id>`.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zhost_cli.errors import ConfigError

APP_NAME = "zhost-cli"
CONFIG_FILE_NAME = "config.json"
DEFAULT_TIMEOUT = 60
DEFAULT_USER_ID = "1"
API_VERSION = "3"


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    user_id: str = DEFAULT_USER_ID
    timeout: int = DEFAULT_TIMEOUT


def xdg_config_home() -> Path:
    value = os.environ.get("XDG_CONFIG_HOME")
    return Path(value) if value else Path.home() / ".config"


def default_config_path() -> Path:
    return xdg_config_home() / APP_NAME / CONFIG_FILE_NAME


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in config file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config file {path} must contain a JSON object")
    return data


def write_config(
    base_url: str,
    api_key_command: str,
    user_id: str,
    path: Path | None = None,
) -> Path:
    if not base_url.strip():
        raise ConfigError("base_url must not be empty")
    if not api_key_command.strip():
        raise ConfigError("api_key_command must not be empty")
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "base_url": base_url.rstrip("/"),
        "api_key_command": api_key_command,
        "user_id": user_id,
    }
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return config_path


def run_key_command(command: str) -> str | None:
    argv = shlex.split(command)
    if not argv:
        return None
    try:
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.splitlines()[0].strip() if result.stdout.strip() else None


def _string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def load_config(path: Path | None = None) -> Config:
    config_path = path or default_config_path()
    data = load_json(config_path)

    base_url = (
        os.environ.get("ZHOST_BASE_URL")
        or os.environ.get("ZHOST_URL")
        or _string(data, "base_url")
        or _string(data, "url")
    )
    if not base_url:
        raise ConfigError(f"zhost base URL missing; run {APP_NAME} setup")

    api_key = os.environ.get("ZHOST_API_KEY") or _string(data, "api_key")
    if not api_key:
        command = os.environ.get("ZHOST_API_KEY_COMMAND") or _string(
            data, "api_key_command"
        )
        if command:
            api_key = run_key_command(command)
    if not api_key:
        raise ConfigError("zhost API key missing; set ZHOST_API_KEY or api_key_command")

    user_id = (
        os.environ.get("ZHOST_USER_ID") or _string(data, "user_id") or DEFAULT_USER_ID
    )

    timeout = DEFAULT_TIMEOUT
    timeout_raw = os.environ.get("ZHOST_TIMEOUT") or data.get("timeout")
    if timeout_raw is not None:
        try:
            timeout = int(timeout_raw)
        except (TypeError, ValueError):
            raise ConfigError(f"invalid timeout: {timeout_raw!r}") from None

    return Config(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        user_id=user_id,
        timeout=timeout,
    )
