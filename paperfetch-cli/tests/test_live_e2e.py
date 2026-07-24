"""Opt-in live end-to-end tests for paperfetch download sources.

These tests hit public metadata/PDF services and, for publisher paths, launch a
real browser. They stay out of normal CI unless explicitly enabled.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from paperfetch_cli.errors import EXIT_OK
from paperfetch_cli.main import main

if TYPE_CHECKING:
    from collections.abc import Sequence


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}


LIVE = pytest.mark.skipif(
    not _env_enabled("PAPERFETCH_LIVE"),
    reason="set PAPERFETCH_LIVE=1 to run networked paperfetch e2e tests",
)
BROWSER_LIVE = pytest.mark.skipif(
    not _env_enabled("PAPERFETCH_LIVE_BROWSER"),
    reason="set PAPERFETCH_LIVE_BROWSER=1 to launch browser publisher e2e tests",
)


def _json_get(
    args: Sequence[str], capsys: pytest.CaptureFixture[str]
) -> dict[str, object]:
    rc = main(["get", *args, "--json"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK, captured.err or captured.out
    return cast("dict[str, object]", json.loads(captured.out))


def _assert_pdf(path: object) -> Path:
    assert isinstance(path, str)
    pdf = Path(path)
    assert pdf.is_file()
    assert pdf.read_bytes().startswith(b"%PDF-")
    return pdf


@LIVE
@pytest.mark.parametrize(
    ("target", "source"),
    [
        ("arXiv:2401.12345", "arxiv"),
        ("PMC3531190", "europepmc"),
        ("10.21105/joss.03021", "oa"),
    ],
)
def test_live_get_downloads_direct_pdf_sources(
    target: str,
    source: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    manifest = _json_get([target, "--pdf", "--out", str(tmp_path)], capsys)
    pdf = manifest.get("pdf")
    assert isinstance(pdf, dict)
    assert pdf.get("via") == source
    _assert_pdf(pdf.get("path"))


@BROWSER_LIVE
@pytest.mark.parametrize(
    ("target", "source"),
    [
        ("https://www.nature.com/articles/s41586-024-08025-4", "citation_pdf_url"),
        (
            "https://www.cell.com/cell/fulltext/S0092-8674(24)00467-7",
            "citation_pdf_url",
        ),
        ("10.1126/science.aea2535", "adapter"),
    ],
)
def test_live_get_downloads_browser_pdf_sources(
    target: str,
    source: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    manifest = _json_get([target, "--pdf", "--out", str(tmp_path)], capsys)
    pdf = manifest.get("pdf")
    assert isinstance(pdf, dict)
    assert pdf.get("via") == source
    _assert_pdf(pdf.get("path"))


@BROWSER_LIVE
@pytest.mark.skipif(
    sys.platform != "linux" or not _env_enabled("PAPERFETCH_LIVE_SCIENCEDIRECT"),
    reason=(
        "set PAPERFETCH_LIVE_BROWSER=1 and PAPERFETCH_LIVE_SCIENCEDIRECT=1 "
        "on Linux/Xvfb to test ScienceDirect Cloudflare"
    ),
)
@pytest.mark.xfail(
    reason="ScienceDirect PDF byte return is best-effort and may need manual handoff",
    strict=False,
)
def test_live_sciencedirect_pdf_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    manifest = _json_get(
        ["10.1016/j.bmc.2024.117837", "--pdf", "--out", str(tmp_path)], capsys
    )
    pdf = manifest.get("pdf")
    assert isinstance(pdf, dict)
    assert pdf.get("via") == "sciencedirect"
    _assert_pdf(pdf.get("path"))
