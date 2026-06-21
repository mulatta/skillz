"""Tests for DOI normalization and OpenAlex parsing (no network)."""

from __future__ import annotations

from paperfetch_cli.resolve import (
    normalize_doi,
    parse_openalex,
    sciencedirect_pdf_url,
)

# Real pdfDownload island from a rendered ScienceDirect article page.
SD_HTML = (
    '...,"pdfDownload":{"isPdfFullText":false,"urlMetadata":{"queryParams":'
    '{"md5":"03477c0f65b59326f9b20869dda0d791",'
    '"pid":"1-s2.0-S0968089624002517-main.pdf"},"pii":"S0968089624002517",'
    '"pdfExtension":"/pdfft","path":"science/article/pii"}},...'
)

SAMPLE_OPENALEX: dict[str, object] = {
    "title": "Scalable watermarking",
    "publication_year": 2024,
    "authorships": [
        {"author": {"display_name": "Ada Lovelace"}},
        {"author": {"display_name": "Alan Turing"}},
    ],
    "primary_location": {
        "source": {"display_name": "Nature"},
        "landing_page_url": "https://www.nature.com/articles/s41586-024-08025-4",
    },
    "best_oa_location": {"pdf_url": "https://example.org/paper.pdf"},
}


def test_normalize_doi() -> None:
    assert (
        normalize_doi("https://doi.org/10.1016/J.CELL.2024.01.001")
        == "10.1016/j.cell.2024.01.001"
    )
    assert normalize_doi("doi:10.1126/science.aea2535") == "10.1126/science.aea2535"
    assert normalize_doi("no doi here") is None


def test_parse_openalex() -> None:
    meta = parse_openalex(SAMPLE_OPENALEX, "10.1/x")
    assert meta.doi == "10.1/x"
    assert meta.title == "Scalable watermarking"
    assert meta.authors == ("Ada Lovelace", "Alan Turing")
    assert meta.journal == "Nature"
    assert meta.year == 2024
    assert meta.oa_pdf_url == "https://example.org/paper.pdf"
    assert meta.landing_url == "https://www.nature.com/articles/s41586-024-08025-4"


def test_sciencedirect_pdf_url() -> None:
    url = sciencedirect_pdf_url(
        SD_HTML, "https://www.sciencedirect.com/science/article/pii/S0968089624002517"
    )
    assert url == (
        "https://www.sciencedirect.com/science/article/pii/S0968089624002517/pdfft"
        "?md5=03477c0f65b59326f9b20869dda0d791"
        "&pid=1-s2.0-S0968089624002517-main.pdf"
    )


def test_sciencedirect_pdf_url_absent() -> None:
    assert sciencedirect_pdf_url("<html>no island</html>", "https://x.test") is None


def test_parse_openalex_handles_missing_fields() -> None:
    meta = parse_openalex({}, "10.1/y")
    assert meta.doi == "10.1/y"
    assert meta.title == ""
    assert meta.authors == ()
    assert meta.oa_pdf_url is None
