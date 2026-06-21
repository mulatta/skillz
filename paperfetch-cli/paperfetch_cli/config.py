"""Runtime configuration: CLI flags layered over a saved config file.

``setup`` writes ``$XDG_CONFIG_HOME/paperfetch-cli/config.json`` once (profile
dir, chromium path) so the browser/auth options need not be passed per call.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

DEFAULT_TIMEOUT = 60
# The Nix wrapper sets PAPERFETCH_CHROMIUM to the bundled Chromium on Linux.
_CHROMIUM_NAMES = ("chromium", "chromium-browser", "google-chrome-stable", "chrome")


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "paperfetch-cli" / "config.json"


@dataclass(frozen=True)
class BrowserConfig:
    """Everything the browser engine needs for one invocation."""

    headful: bool = True
    executable: str | None = None
    cookies: str | None = None
    profile: str | None = None
    headers: tuple[tuple[str, str], ...] = ()
    timeout: int = DEFAULT_TIMEOUT


def parse_headers(raw: list[str]) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for item in raw:
        key, sep, value = item.partition(":")
        if not sep:
            msg = f"invalid --header (want 'Key: Value'): {item!r}"
            raise ValueError(msg)
        out.append((key.strip(), value.strip()))
    return tuple(out)


def load_file_config() -> dict[str, object]:
    path = config_path()
    if not path.is_file():
        return {}
    loaded: object = json.loads(path.read_text())
    return loaded if isinstance(loaded, dict) else {}


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def resolve_chromium(arg: object, saved: dict[str, object]) -> str | None:
    """--executable, then saved config, then the wrapper env, then PATH."""
    explicit = (
        _as_str(arg)
        or _as_str(saved.get("chromium"))
        or os.environ.get("PAPERFETCH_CHROMIUM")
    )
    if explicit:
        return explicit
    for name in _CHROMIUM_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def browser_config_from_args(args: argparse.Namespace) -> BrowserConfig:
    saved = load_file_config()
    return BrowserConfig(
        headful=bool(args.headful),
        executable=resolve_chromium(args.executable, saved),
        cookies=_as_str(args.cookies),
        profile=_as_str(args.profile) or _as_str(saved.get("profile_dir")),
        headers=parse_headers(list(args.header or [])),
        timeout=int(args.timeout),
    )
