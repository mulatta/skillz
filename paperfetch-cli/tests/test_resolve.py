"""Tests for identifier normalization and OA metadata parsing (no network)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from paperfetch_cli.errors import CLIError
from paperfetch_cli.resolve import (
    arxiv_paper_meta,
    europepmc_search_url,
    normalize_arxiv_id,
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
    parse_europepmc,
    parse_identifier,
    parse_openalex,
    parse_pmc_oa_pdf,
    parse_unpaywall,
    resolve_arxiv_metadata,
    resolve_metadata,
    sciencedirect_pdf_url,
)

if TYPE_CHECKING:
    import pytest

# Real pdfDownload island from a rendered ScienceDirect article page.
SD_HTML = (
    '...,"pdfDownload":{"isPdfFullText":false,"urlMetadata":{"queryParams":'
    '{"md5":"03477c0f65b59326f9b20869dda0d791",'
    '"pid":"1-s2.0-S0968089624002517-main.pdf"},"pii":"S0968089624002517",'
    '"pdfExtension":"/pdfft","path":"science/article/pii"}},...'
)

SAMPLE_ARXIV_ATOM = """\
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <title>Native identifiers for open access</title>
    <published>2024-01-02T00:00:00Z</published>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <arxiv:doi>10.1234/example</arxiv:doi>
    <arxiv:journal_ref>Journal of Legal Fetching</arxiv:journal_ref>
  </entry>
</feed>
"""

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

SAMPLE_EUROPEPMC: dict[str, object] = {
    "resultList": {
        "result": [
            {
                "doi": "10.1371/journal.pone.0000308",
                "pmid": "17375194",
                "pmcid": "PMC1817623",
                "title": "An open access paper",
                "journalTitle": "PLOS ONE",
                "pubYear": "2007",
                "isOpenAccess": "Y",
                "authorList": {
                    "author": [
                        {"fullName": "Jane Doe"},
                        {"fullName": "John Roe"},
                    ]
                },
                "fullTextUrlList": {
                    "fullTextUrl": [
                        {
                            "availability": "Open access",
                            "availabilityCode": "OA",
                            "documentStyle": "html",
                            "site": "Europe_PMC",
                            "url": "https://europepmc.org/articles/PMC1817623",
                        },
                        {
                            "availability": "Open access",
                            "availabilityCode": "OA",
                            "documentStyle": "pdf",
                            "site": "Europe_PMC",
                            "url": "https://europepmc.org/articles/PMC1817623?pdf=render",
                        },
                    ]
                },
            }
        ]
    }
}

SAMPLE_PMC_OA = """
<OA>
  <records returned-count="1" total-count="1">
    <record id="PMC1817623" license="cc by" retracted="no">
      <link format="tgz" href="ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/aa/bb/example.tar.gz" />
      <link format="pdf" href="ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/aa/bb/example.pdf" />
    </record>
  </records>
</OA>
"""

SAMPLE_UNPAYWALL: dict[str, object] = {
    "title": "Scalable watermarking from Unpaywall",
    "year": 2023,
    "journal_name": "OA Journal",
    "doi_url": "https://doi.org/10.1/x",
    "z_authors": [{"given": "Grace", "family": "Hopper"}],
    "best_oa_location": {
        "url_for_landing_page": "https://repository.example.org/item/1",
        "url_for_pdf": "https://repository.example.org/paper.pdf",
        "host_type": "repository",
    },
}


def test_normalize_doi() -> None:
    assert (
        normalize_doi("https://doi.org/10.1016/J.CELL.2024.01.001")
        == "10.1016/j.cell.2024.01.001"
    )
    assert normalize_doi("doi:10.1126/science.aea2535") == "10.1126/science.aea2535"
    assert (
        normalize_doi(
            "https://www.biorxiv.org/content/10.1101/2024.01.02.123456v2.full"
        )
        == "10.1101/2024.01.02.123456"
    )
    assert normalize_doi("no doi here") is None


def test_normalize_arxiv_id() -> None:
    assert normalize_arxiv_id("2401.12345") == "2401.12345"
    assert normalize_arxiv_id("arXiv:hep-th/9901001v2") == "hep-th/9901001v2"
    assert normalize_arxiv_id("https://arxiv.org/pdf/2401.12345.pdf") == "2401.12345"
    assert normalize_arxiv_id("not an arxiv id") is None


def test_parse_identifier_prefers_specific_kinds() -> None:
    doi = parse_identifier("https://doi.org/10.1234/ABC")
    assert doi is not None
    assert doi.kind == "doi"
    assert doi.value == "10.1234/abc"
    assert doi.is_url
    arxiv = parse_identifier("arXiv:2401.12345")
    assert arxiv is not None
    assert arxiv.kind == "arxiv"
    assert arxiv.value == "2401.12345"
    pmcid = parse_identifier("PMC1234567")
    assert pmcid is not None
    assert pmcid.kind == "pmcid"
    assert parse_identifier("https://example.org/article") is not None
    assert parse_identifier("not supported") is None


def test_arxiv_meta_direct_url() -> None:
    meta = arxiv_paper_meta("2401.12345")
    assert meta.oa_pdf_url == "https://arxiv.org/pdf/2401.12345.pdf"
    assert meta.landing_url == "https://arxiv.org/abs/2401.12345"
    assert meta.oa_pdf_source == "arxiv"


def test_resolve_arxiv_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "paperfetch_cli.resolve._get_text",
        lambda _url, _accept: SAMPLE_ARXIV_ATOM,
    )
    meta = resolve_arxiv_metadata("2401.12345")
    assert meta.arxiv_id == "2401.12345"
    assert meta.doi == "10.1234/example"
    assert meta.title == "Native identifiers for open access"
    assert meta.authors == ("Ada Lovelace", "Alan Turing")
    assert meta.journal == "Journal of Legal Fetching"
    assert meta.year == 2024
    assert meta.oa_pdf_url == "https://arxiv.org/pdf/2401.12345.pdf"


def test_normalize_pmid_and_pmcid() -> None:
    assert normalize_pmid("PMID: 17375194") == "17375194"
    assert normalize_pmid("https://pubmed.ncbi.nlm.nih.gov/17375194/") == "17375194"
    assert normalize_pmid("17375194") == "17375194"
    assert normalize_pmid("no pmid here") is None
    assert normalize_pmcid("PMCID: pmc1817623") == "PMC1817623"
    assert (
        normalize_pmcid("https://pmc.ncbi.nlm.nih.gov/articles/PMC1817623/")
        == "PMC1817623"
    )
    assert normalize_pmcid("no pmcid here") is None


def test_parse_openalex() -> None:
    meta = parse_openalex(SAMPLE_OPENALEX, "10.1/x")
    assert meta.doi == "10.1/x"
    assert meta.title == "Scalable watermarking"
    assert meta.authors == ("Ada Lovelace", "Alan Turing")
    assert meta.journal == "Nature"
    assert meta.year == 2024
    assert meta.oa_pdf_url == "https://example.org/paper.pdf"
    assert meta.landing_url == "https://www.nature.com/articles/s41586-024-08025-4"


def test_parse_europepmc_prefers_open_access_pdf() -> None:
    meta = parse_europepmc(SAMPLE_EUROPEPMC, doi="10.1371/journal.pone.0000308")
    assert meta is not None
    assert meta.doi == "10.1371/journal.pone.0000308"
    assert meta.pmid == "17375194"
    assert meta.pmcid == "PMC1817623"
    assert meta.title == "An open access paper"
    assert meta.authors == ("Jane Doe", "John Roe")
    assert meta.journal == "PLOS ONE"
    assert meta.year == 2007
    assert meta.oa_pdf_url == "https://europepmc.org/articles/PMC1817623?pdf=render"
    assert meta.oa_pdf_source == "europepmc"
    assert meta.landing_url == "https://europepmc.org/articles/PMC1817623"


def test_parse_europepmc_synthesizes_pdf_for_oa_pmcid() -> None:
    data: dict[str, object] = {
        "resultList": {
            "result": [
                {
                    "pmcid": "PMC1817623",
                    "title": "OA without explicit PDF",
                    "isOpenAccess": "Y",
                }
            ]
        }
    }
    meta = parse_europepmc(data, pmcid="PMC1817623")
    assert meta is not None
    assert meta.oa_pdf_url == "https://europepmc.org/articles/PMC1817623?pdf=render"
    assert meta.oa_landing_url == "https://europepmc.org/articles/PMC1817623"


def test_parse_europepmc_empty_result() -> None:
    assert parse_europepmc({"resultList": {"result": []}}, doi="10.1/nope") is None


def test_europepmc_search_url_encodes_identifier_queries() -> None:
    assert "query=DOI%3A%2210.1371%2Fjournal.pone.0000308%22" in europepmc_search_url(
        doi="10.1371/journal.pone.0000308"
    )
    assert "query=EXT_ID%3A17375194+AND+SRC%3AMED" in europepmc_search_url(
        pmid="17375194"
    )
    assert "query=PMCID%3APMC1817623" in europepmc_search_url(pmcid="PMC1817623")


def test_parse_pmc_oa_pdf_converts_ftp_to_https() -> None:
    assert parse_pmc_oa_pdf(SAMPLE_PMC_OA) == (
        "https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/aa/bb/example.pdf"
    )


def test_parse_pmc_oa_pdf_skips_retracted_records() -> None:
    xml = """
    <OA><records><record id="PMC1" retracted="yes">
      <link format="pdf" href="ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/x.pdf" />
    </record></records></OA>
    """
    assert parse_pmc_oa_pdf(xml) is None


def test_parse_unpaywall() -> None:
    meta = parse_unpaywall(SAMPLE_UNPAYWALL, "10.1/x")
    assert meta.doi == "10.1/x"
    assert meta.title == "Scalable watermarking from Unpaywall"
    assert meta.authors == ("Grace Hopper",)
    assert meta.journal == "OA Journal"
    assert meta.year == 2023
    assert meta.oa_pdf_url == "https://repository.example.org/paper.pdf"
    assert meta.oa_pdf_source == "unpaywall"
    assert meta.landing_url == "https://repository.example.org/item/1"


def test_parse_unpaywall_falls_back_to_oa_locations() -> None:
    data: dict[str, object] = {
        "best_oa_location": {"url_for_landing_page": "https://landing.example.org"},
        "oa_locations": [
            {"url_for_pdf": "https://mirror.example.org/paper.pdf"},
        ],
    }
    meta = parse_unpaywall(data, "10.1/x")
    assert meta.oa_pdf_url == "https://mirror.example.org/paper.pdf"
    assert meta.oa_pdf_source == "unpaywall"
    assert meta.landing_url == "https://landing.example.org"


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


def test_resolve_metadata_merges_unpaywall_pdf_when_openalex_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    openalex = dict(SAMPLE_OPENALEX)
    openalex["best_oa_location"] = {}

    def fake_get_json(url: str, source: str = "metadata") -> dict[str, object]:
        if "openalex" in url:
            return openalex
        assert "email=dev%40example.org" in url
        assert source == "Unpaywall"
        return SAMPLE_UNPAYWALL

    monkeypatch.setattr("paperfetch_cli.resolve._get_json", fake_get_json)
    meta = resolve_metadata("10.1/x", "dev@example.org")
    assert meta.title == "Scalable watermarking"
    assert meta.authors == ("Ada Lovelace", "Alan Turing")
    assert meta.journal == "Nature"
    assert meta.year == 2024
    assert meta.oa_pdf_url == "https://repository.example.org/paper.pdf"
    assert meta.landing_url == "https://www.nature.com/articles/s41586-024-08025-4"


def test_resolve_metadata_uses_unpaywall_when_openalex_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_json(url: str, source: str = "metadata") -> dict[str, object]:
        if "openalex" in url:
            msg = "OpenAlex lookup failed"
            raise CLIError(msg, 2)
        return SAMPLE_UNPAYWALL

    monkeypatch.setattr("paperfetch_cli.resolve._get_json", fake_get_json)
    meta = resolve_metadata("10.1/x", "dev@example.org")
    assert meta.title == "Scalable watermarking from Unpaywall"
    assert meta.oa_pdf_url == "https://repository.example.org/paper.pdf"


def test_resolve_metadata_skips_unpaywall_without_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    openalex = dict(SAMPLE_OPENALEX)
    openalex["best_oa_location"] = {}

    def fake_get_json(url: str, source: str = "metadata") -> dict[str, object]:
        calls.append(url)
        return openalex

    monkeypatch.setattr("paperfetch_cli.resolve._get_json", fake_get_json)
    meta = resolve_metadata("10.1/x")
    assert meta.oa_pdf_url is None
    assert len(calls) == 1
