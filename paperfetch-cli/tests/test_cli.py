"""Tests for the command surface, config, and the metadata path of ``get``.

The browser-driven paths (``render`` / ``grab``, paywalled full text) are
integration-tested against a real browser on the deploy host, not here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from paperfetch_cli import main as main_mod
from paperfetch_cli.config import (
    config_path,
    load_file_config,
    parse_headers,
    unpaywall_email_from_args,
)
from paperfetch_cli.errors import EXIT_OK, EXIT_UNRESOLVED, EXIT_USAGE, CLIError
from paperfetch_cli.main import build_parser, main
from paperfetch_cli.resolve import PaperMeta, arxiv_paper_meta

if TYPE_CHECKING:
    from pathlib import Path


def test_get_rejects_non_identifier(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["get", "not a doi"])
    captured = capsys.readouterr()
    assert rc == EXIT_USAGE
    assert "DOI" in captured.err


def test_get_accepts_arxiv_identifier(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(main_mod, "resolve_arxiv_metadata", arxiv_paper_meta)
    rc = main(["get", "arXiv:2401.12345", "--json"])
    out = capsys.readouterr().out
    assert rc == EXIT_OK
    assert '"arxiv": "2401.12345"' in out
    assert '"url": "https://arxiv.org/pdf/2401.12345.pdf"' in out
    assert '"via": "arxiv"' in out


def test_get_rejects_markdown_json_stdout_mix(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(main_mod, "resolve_arxiv_metadata", arxiv_paper_meta)
    rc = main(["get", "arXiv:2401.12345", "--md", "--json"])
    captured = capsys.readouterr()
    assert rc == EXIT_USAGE
    assert captured.out == ""
    assert "cannot combine --json with --md" in captured.err


def test_get_reports_suppressed_metadata_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_metadata(_doi: str, _email: str | None = None) -> PaperMeta:
        msg = "OpenAlex lookup failed"
        raise CLIError(msg, EXIT_UNRESOLVED)

    def fail_europepmc(**_kwargs: object) -> PaperMeta:
        msg = "Europe PMC lookup found no matching record"
        raise CLIError(msg, EXIT_UNRESOLVED)

    monkeypatch.setattr(main_mod, "resolve_metadata", fail_metadata)
    monkeypatch.setattr(main_mod, "resolve_europepmc", fail_europepmc)
    rc = main(["get", "10.1234/abc", "--json"])
    out = capsys.readouterr().out
    assert rc == EXIT_OK
    assert "OpenAlex lookup failed" in out
    assert "Europe PMC lookup found no matching record" in out


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("PMID:17375194", '"pmid": "17375194"'),
        ("PMC1817623", '"pmcid": "PMC1817623"'),
    ],
)
def test_get_accepts_pubmed_identifiers(
    target: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    meta = PaperMeta(
        doi="10.1371/journal.pone.0000308",
        title="OA Paper",
        pmid="17375194",
        pmcid="PMC1817623",
        oa_pdf_url="https://europepmc.org/articles/PMC1817623?pdf=render",
        oa_pdf_source="europepmc",
        landing_url="https://europepmc.org/articles/PMC1817623",
    )
    monkeypatch.setattr(main_mod, "resolve_europepmc", lambda **_kwargs: meta)
    rc = main(["get", target, "--json"])
    out = capsys.readouterr().out
    assert rc == EXIT_OK
    assert expected in out
    assert '"via": "europepmc"' in out


def test_get_keeps_europepmc_landing_when_direct_pdf_returns_html(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    meta = PaperMeta(
        doi="10.1371/journal.pone.0000308",
        title="OA Paper",
        pmcid="PMC1817623",
        oa_pdf_url="https://europepmc.org/articles/PMC1817623?pdf=render",
        oa_pdf_source="europepmc",
        landing_url="https://europepmc.org/articles/PMC1817623",
        oa_landing_url="https://europepmc.org/articles/PMC1817623",
    )
    seen: dict[str, str] = {}
    monkeypatch.setattr(
        main_mod,
        "resolve_metadata",
        lambda _doi, _email=None: PaperMeta(doi="10.1371/journal.pone.0000308"),
    )
    monkeypatch.setattr(main_mod, "resolve_europepmc", lambda **_kwargs: meta)

    def fail_download(_url: str, _dest: Path) -> None:
        msg = "OA link returned an HTML page, not a PDF"
        raise CLIError(msg, EXIT_UNRESOLVED)

    def fake_browser_get(
        _args: object,
        _meta: PaperMeta,
        _manifest: dict[str, object],
        landing: str,
        _warnings: list[str],
    ) -> tuple[str | None, int]:
        seen["landing"] = landing
        return None, EXIT_OK

    monkeypatch.setattr(main_mod, "download_file", fail_download)
    monkeypatch.setattr(main_mod, "_browser_get", fake_browser_get)
    rc = main(
        [
            "get",
            "10.1371/journal.pone.0000308",
            "--pdf",
            "--json",
            "--out",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert rc == EXIT_OK
    assert seen["landing"] == "https://europepmc.org/articles/PMC1817623"
    assert "OA link returned an HTML page" in out


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
    rc = main(
        [
            "setup",
            "--profile-dir",
            "/p",
            "--chromium",
            "/c",
            "--unpaywall-email",
            "dev@example.org",
        ]
    )
    capsys.readouterr()
    assert rc == EXIT_OK
    assert config_path() == tmp_path / "paperfetch-cli" / "config.json"
    assert load_file_config() == {
        "profile_dir": "/p",
        "chromium": "/c",
        "unpaywall_email": "dev@example.org",
    }


def test_load_file_config_reports_corrupt_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_path().parent.mkdir(parents=True)
    config_path().write_text("not-json")
    with pytest.raises(CLIError, match="invalid config JSON"):
        load_file_config()


def test_unpaywall_email_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_path().parent.mkdir(parents=True)
    config_path().write_text('{"unpaywall_email": "saved@example.org"}')
    monkeypatch.setenv("PAPERFETCH_UNPAYWALL_EMAIL", "env@example.org")
    args = build_parser().parse_args(
        ["get", "10.1234/abc", "--unpaywall-email", "cli@example.org"]
    )
    assert unpaywall_email_from_args(args) == "cli@example.org"
    args = build_parser().parse_args(["get", "10.1234/abc"])
    assert unpaywall_email_from_args(args) == "env@example.org"
    monkeypatch.delenv("PAPERFETCH_UNPAYWALL_EMAIL")
    assert unpaywall_email_from_args(args) == "saved@example.org"
