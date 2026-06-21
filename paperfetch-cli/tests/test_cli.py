"""Tests for the command surface, config, and the metadata path of ``get``.

The browser-driven paths (``render`` / ``grab``, paywalled full text) are
integration-tested against a real browser on the deploy host, not here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from paperfetch_cli import main as main_mod
from paperfetch_cli.config import config_path, load_file_config, parse_headers
from paperfetch_cli.errors import EXIT_OK, EXIT_USAGE
from paperfetch_cli.main import build_parser, main
from paperfetch_cli.resolve import PaperMeta

if TYPE_CHECKING:
    from pathlib import Path

MINIMAL_INVOCATIONS = (
    ["get", "10.1016/j.cell.2024.01.001"],
    ["render", "https://example.org/x"],
    ["grab", "https://example.org/x.pdf", "--out", "x.pdf"],
    ["setup"],
)


def test_each_command_parses_and_sets_a_handler() -> None:
    parser = build_parser()
    for argv in MINIMAL_INVOCATIONS:
        args = parser.parse_args(argv)
        assert callable(args.handler)


def test_no_command_prints_help_and_returns_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main([])
    captured = capsys.readouterr()
    assert rc == EXIT_USAGE
    assert "paperfetch-cli" in captured.out


def test_get_rejects_non_doi(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["get", "not a doi"])
    captured = capsys.readouterr()
    assert rc == EXIT_USAGE
    assert "DOI" in captured.err


def test_get_emits_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    meta = PaperMeta(
        doi="10.1234/abc",
        title="A Paper",
        authors=("Ada L",),
        journal="J",
        year=2024,
        oa_pdf_url="https://example.org/x.pdf",
    )
    monkeypatch.setattr(main_mod, "resolve_metadata", lambda _doi: meta)
    rc = main(["get", "10.1234/abc", "--json"])
    out = capsys.readouterr().out
    assert rc == EXIT_OK
    assert '"doi": "10.1234/abc"' in out
    assert '"via": "oa"' in out


def test_parse_headers_round_trip() -> None:
    assert parse_headers(["X-A: 1", "X-B:2"]) == (("X-A", "1"), ("X-B", "2"))
    with pytest.raises(ValueError, match="invalid --header"):
        parse_headers(["no-colon"])


def test_setup_writes_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    rc = main(["setup", "--profile-dir", "/p", "--chromium", "/c"])
    capsys.readouterr()
    assert rc == EXIT_OK
    assert config_path() == tmp_path / "paperfetch-cli" / "config.json"
    assert load_file_config() == {"profile_dir": "/p", "chromium": "/c"}
