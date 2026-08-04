# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from . import xmlsafe
from .atomic import atomic_write_bytes, same_file
from .document import DrawioDocument, sha256_file
from .png import assert_png, repair_png_iend
from .validate import validate_document


def _validate_render_options(
    fmt: str,
    page_index: int | None,
    width: int | None,
    transparent: bool,
) -> None:
    if fmt not in {"png", "svg", "pdf"}:
        raise ValueError("format must be png, svg, or pdf")
    if page_index is not None and page_index < 0:
        raise ValueError("page index must be non-negative")
    if width is not None and width <= 0:
        raise ValueError("width must be positive")
    if transparent and fmt != "png":
        raise ValueError("transparent background is supported only for PNG")


def render_diagram(
    source: Path,
    output: Path,
    *,
    fmt: str,
    drawio: str | None = None,
    page_index: int | None = None,
    width: int | None = None,
    transparent: bool = False,
) -> None:
    _validate_render_options(fmt, page_index, width, transparent)
    if same_file(source, output):
        raise ValueError("render output must not overwrite source file")
    before = sha256_file(source)
    validation = validate_document(DrawioDocument.from_file(source))
    if validation.errors:
        raise ValueError("source validation failed: " + "; ".join(validation.errors))

    drawio_bin = drawio or os.environ.get("DRAWIO_CLI_DRAWIO", "drawio")
    with tempfile.TemporaryDirectory(prefix="drawio-cli-render-") as tmp:
        tmp_out = Path(tmp) / f"output.{fmt}"
        cmd = _render_command(
            drawio_bin,
            source,
            tmp_out,
            fmt=fmt,
            page_index=page_index,
            width=width,
            transparent=transparent,
        )
        result = subprocess.run(
            cmd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_render_env(Path(tmp)),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"drawio export failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        _validate_render_output(tmp_out, fmt)
        if sha256_file(source) != before:
            raise RuntimeError("source changed during render")
        atomic_write_bytes(output, tmp_out.read_bytes())


def _render_env(tmp: Path) -> dict[str, str]:
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(tmp / "config"),
        "XDG_CACHE_HOME": str(tmp / "cache"),
    }
    if platform.system() == "Darwin":
        # Electron's safeStorage uses ~/Library/Keychains on macOS. A temporary
        # HOME hides the user's unlocked login keychain and makes draw.io fail
        # before export with "A keychain cannot be found".
        return env
    env["HOME"] = str(tmp)
    return env


def _render_command(
    drawio_bin: str,
    source: Path,
    output: Path,
    *,
    fmt: str,
    page_index: int | None,
    width: int | None,
    transparent: bool,
) -> list[str]:
    _validate_render_options(fmt, page_index, width, transparent)
    cmd = [drawio_bin, "--export", "--format", fmt, "--output", str(output)]
    if page_index is not None:
        cmd.extend(["--page-index", str(page_index)])
    if width is not None:
        cmd.extend(["--width", str(width)])
    if transparent:
        cmd.append("--transparent")
    cmd.append(str(source))
    return cmd


def _validate_render_output(path: Path, fmt: str) -> None:
    if not path.exists():
        raise RuntimeError(f"drawio did not create {path}")
    if fmt == "png":
        repair_png_iend(path)
        assert_png(path)
        return
    if fmt == "svg":
        try:
            root = xmlsafe.fromstring(path.read_bytes())
        except ET.ParseError as exc:
            raise ValueError("invalid SVG output") from exc
        if root.tag.rsplit("}", 1)[-1] != "svg":
            raise ValueError("invalid SVG output")
        return
    pdf = path.read_bytes()
    if not pdf.startswith(b"%PDF") or not pdf.rstrip().endswith(b"%%EOF"):
        raise ValueError("invalid PDF output")
