"""Configuration and token resolution."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from linkwarden_cli.errors import ConfigError

APP_NAME = "linkwarden-cli"
CONFIG_FILE_NAME = "config.json"
DEFAULT_TIMEOUT = 30


@dataclass(frozen=True)
class Config:
    base_url: str
    token: str
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


def write_config(base_url: str, token_command: str, path: Path | None = None) -> Path:
    if not base_url.strip():
        raise ConfigError("base_url must not be empty")
    if not token_command.strip():
        raise ConfigError("token_command must not be empty")
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"base_url": base_url.rstrip("/"), "token_command": token_command}
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return config_path


def run_token_command(command: str) -> str | None:
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
        os.environ.get("LINKWARDEN_BASE_URL")
        or os.environ.get("LINKWARDEN_URL")
        or _string(data, "base_url")
        or _string(data, "url")
    )
    if not base_url:
        raise ConfigError(f"Linkwarden base URL missing; run {APP_NAME} setup")

    token = os.environ.get("LINKWARDEN_TOKEN") or _string(data, "token")
    if not token:
        command = os.environ.get("LINKWARDEN_TOKEN_COMMAND") or _string(data, "token_command")
        if command:
            token = run_token_command(command)
    if not token:
        raise ConfigError("Linkwarden token missing; set LINKWARDEN_TOKEN or token_command")

    timeout = DEFAULT_TIMEOUT
    timeout_raw = os.environ.get("LINKWARDEN_TIMEOUT") or data.get("timeout")
    if timeout_raw is not None:
        try:
            timeout = int(timeout_raw)
        except (TypeError, ValueError):
            raise ConfigError(f"invalid timeout: {timeout_raw!r}") from None

    return Config(base_url=base_url.rstrip("/"), token=token, timeout=timeout)
