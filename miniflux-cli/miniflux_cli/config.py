"""Configuration loading for miniflux-cli."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Config:
    api_url: str
    token: str


class ConfigError(RuntimeError):
    """Configuration could not be loaded."""


def xdg_config_home() -> Path:
    value = os.environ.get("XDG_CONFIG_HOME")
    if value:
        return Path(value)
    return Path.home() / ".config"


def xdg_cache_home() -> Path:
    value = os.environ.get("XDG_CACHE_HOME")
    if value:
        return Path(value)
    return Path.home() / ".cache"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        msg = f"config must be a JSON object: {path}"
        raise ConfigError(msg)
    return data


def _run_token_command(command: str) -> str:
    try:
        result = subprocess.run(
            shlex.split(command),
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"failed to run token command: {command}"
        raise ConfigError(msg) from exc
    token = result.stdout.strip()
    if not token:
        msg = f"token command returned no output: {command}"
        raise ConfigError(msg)
    return token


def default_config_path() -> Path:
    return xdg_config_home() / "miniflux-cli" / "config.json"


def write_config(api_url: str, token_command: str, path: Path | None = None) -> Path:
    config_path = path or default_config_path()
    if not api_url.strip():
        msg = "api_url must not be empty"
        raise ConfigError(msg)
    if not token_command.strip():
        msg = "token_command must not be empty"
        raise ConfigError(msg)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "api_url": api_url.rstrip("/"),
        "token_command": token_command,
    }
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return config_path


def check_token_command(command: str) -> bool:
    try:
        return bool(_run_token_command(command))
    except ConfigError:
        return False


def load_config(path: Path | None = None) -> Config:
    config_path = path or default_config_path()
    data = _load_json(config_path)

    api_url = (
        os.environ.get("MINIFLUX_URL")
        or os.environ.get("MINIFLUX_API_URL")
        or data.get("api_url")
        or data.get("url")
    )
    if not isinstance(api_url, str) or not api_url.strip():
        msg = (
            "Miniflux API URL missing; set MINIFLUX_URL or "
            "$XDG_CONFIG_HOME/miniflux-cli/config.json"
        )
        raise ConfigError(msg)

    token = os.environ.get("MINIFLUX_TOKEN")
    if token is None:
        token_value = data.get("token")
        if isinstance(token_value, str):
            token = token_value

    token_command = os.environ.get("MINIFLUX_TOKEN_COMMAND")
    if token_command is None:
        command_value = data.get("token_command")
        if isinstance(command_value, str):
            token_command = command_value

    if not token and token_command:
        token = _run_token_command(token_command)

    if not token:
        msg = (
            "Miniflux token missing; set MINIFLUX_TOKEN, MINIFLUX_TOKEN_COMMAND, "
            "or config token/token_command"
        )
        raise ConfigError(msg)

    return Config(api_url=api_url.rstrip("/"), token=token)
