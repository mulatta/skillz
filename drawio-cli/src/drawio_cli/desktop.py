from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def _has_gui_session() -> bool:
    if platform.system() == "Darwin":
        return bool(
            os.environ.get("SECURITYSESSIONID") or os.environ.get("LaunchInstanceID")
        )
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def handoff_to_desktop(source: Path, *, drawio: str | None = None) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    if not _has_gui_session():
        raise RuntimeError("draw.io Desktop handoff requires a GUI session")
    drawio_bin = drawio or os.environ.get("DRAWIO_CLI_DRAWIO", "drawio")
    try:
        subprocess.Popen(  # noqa: S603
            [drawio_bin, str(source)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise RuntimeError(f"failed to launch draw.io Desktop: {exc}") from exc
