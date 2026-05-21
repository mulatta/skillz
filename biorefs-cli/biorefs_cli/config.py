"""Configuration helpers for biorefs-cli."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from biorefs_cli.errors import ConfigError, CredentialCheckError

DEFAULT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True, slots=True)
class Config:
    email: str | None = None
    ncbi_api_key_command: str | None = None
    semantic_scholar_api_key_command: str | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_mapping(cls, data: dict[str, object]) -> Config:
        timeout = data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if not isinstance(timeout, int) or timeout <= 0:
            msg = "timeout_seconds must be a positive integer"
            raise ConfigError(msg)
        return cls(
            email=optional_str(data, "email"),
            ncbi_api_key_command=optional_str(data, "ncbi_api_key_command"),
            semantic_scholar_api_key_command=optional_str(
                data,
                "semantic_scholar_api_key_command",
            ),
            timeout_seconds=timeout,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True, slots=True)
class SecretCheckResult:
    name: str
    ok: bool


def default_config_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "biorefs-cli" / "config.json"
    return Path.home() / ".config" / "biorefs-cli" / "config.json"


def load_config(path: Path | None = None) -> Config:
    config_path = path or default_config_path()
    try:
        raw = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config()
    except OSError as exc:
        msg = f"could not read config: {config_path}"
        raise ConfigError(msg) from exc
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"config is not valid JSON: {config_path}"
        raise ConfigError(msg) from exc
    if not isinstance(decoded, dict):
        msg = "config root must be a JSON object"
        raise ConfigError(msg)
    return Config.from_mapping(decoded)


def write_config(config: Config, path: Path | None = None) -> Path:
    config_path = path or default_config_path()
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        body = json.dumps(config.to_json_dict(), indent=2, sort_keys=True)
        fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{body}\n")
        config_path.chmod(0o600)
    except OSError as exc:
        msg = f"could not write config: {config_path}"
        raise ConfigError(msg) from exc
    return config_path


def merge_config(config: Config, updates: dict[str, object]) -> Config:
    data = config.to_json_dict()
    for key, value in updates.items():
        if value is not None:
            data[key] = value
    return Config.from_mapping(data)


def run_secret_command(command: str, *, timeout_seconds: int) -> str:
    try:
        completed = subprocess.run(  # noqa: S602 - config intentionally stores shell commands.
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        msg = "credential command failed"
        raise CredentialCheckError(msg) from exc
    if completed.returncode != 0:
        msg = "credential command failed"
        raise CredentialCheckError(msg)
    secret = completed.stdout.strip()
    if not secret:
        msg = "credential command returned empty stdout"
        raise CredentialCheckError(msg)
    return secret


def check_configured_secrets(config: Config) -> list[SecretCheckResult]:
    results: list[SecretCheckResult] = []
    commands = {
        "ncbi_api_key_command": config.ncbi_api_key_command,
        "semantic_scholar_api_key_command": config.semantic_scholar_api_key_command,
    }
    for name, command in commands.items():
        if command:
            run_secret_command(command, timeout_seconds=config.timeout_seconds)
            results.append(SecretCheckResult(name=name, ok=True))
    return results


def optional_str(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{key} must be a string"
        raise ConfigError(msg)
    return value


def config_to_public_dict(config: Config) -> dict[str, object]:
    return config.to_json_dict()
