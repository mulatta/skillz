from __future__ import annotations

import struct
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest
from drawio_cli.png import PNG_MAGIC, assert_png, repair_png_iend
from drawio_cli.render import (
    _render_command,
    _render_env,
    _validate_render_output,
    render_diagram,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return (
        struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))
    )


def _minimal_png() -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(b"\0\0\0\0\0")
    return (
        PNG_MAGIC
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", pixels)
        + _png_chunk(b"IEND", b"")
    )


def test_render_passes_zero_based_page_index_to_desktop_cli(tmp_path: Path) -> None:
    command = _render_command(
        "drawio",
        tmp_path / "source.drawio",
        tmp_path / "output.png",
        fmt="png",
        page_index=2,
        width=None,
        transparent=False,
    )

    position = command.index("--page-index")
    assert command[position + 1] == "2"


@pytest.mark.parametrize(
    ("fmt", "page_index", "width", "transparent", "message"),
    [
        ("png", -1, None, False, "non-negative"),
        ("png", None, 0, False, "width must be positive"),
        ("svg", None, None, True, "only for PNG"),
    ],
)
def test_render_rejects_invalid_export_options(
    tmp_path: Path,
    fmt: str,
    page_index: int | None,
    width: int | None,
    transparent: bool,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _render_command(
            "drawio",
            tmp_path / "source.drawio",
            tmp_path / f"output.{fmt}",
            fmt=fmt,
            page_index=page_index,
            width=width,
            transparent=transparent,
        )


def test_render_output_validation_checks_structure(tmp_path: Path) -> None:
    valid = _minimal_png()
    missing_iend = tmp_path / "missing-iend.png"
    missing_iend.write_bytes(valid[:-12])
    assert repair_png_iend(missing_iend) is True
    assert_png(missing_iend)

    truncated = tmp_path / "truncated.png"
    truncated.write_bytes(valid[:-13])
    with pytest.raises(ValueError, match="invalid PNG"):
        repair_png_iend(truncated)

    html = tmp_path / "not-svg.svg"
    html.write_text("<html></html>")
    with pytest.raises(ValueError, match="invalid SVG"):
        _validate_render_output(html, "svg")


def test_render_refuses_to_overwrite_source() -> None:
    source = FIXTURES / "minimal.drawio"

    with pytest.raises(ValueError, match="source file"):
        render_diagram(source, source, fmt="png")


def test_render_preserves_home_on_darwin_for_keychain_access(tmp_path: Path) -> None:
    with (
        patch("drawio_cli.render.platform.system", return_value="Darwin"),
        patch.dict(
            "drawio_cli.render.os.environ", {"HOME": "/Users/alice"}, clear=True
        ),
    ):
        env = _render_env(tmp_path)

    assert env["HOME"] == "/Users/alice"
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / "config")
    assert env["XDG_CACHE_HOME"] == str(tmp_path / "cache")


def test_render_uses_temp_home_off_darwin(tmp_path: Path) -> None:
    with (
        patch("drawio_cli.render.platform.system", return_value="Linux"),
        patch.dict("drawio_cli.render.os.environ", {"HOME": "/home/alice"}, clear=True),
    ):
        env = _render_env(tmp_path)

    assert env["HOME"] == str(tmp_path)
