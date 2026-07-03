"""Tests for DOI normalization and OpenAlex parsing (no network)."""

from __future__ import annotations

from paperfetch_cli.resolve import (
    europepmc_search_url,
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
    parse_europepmc,
    parse_openalex,
    parse_pmc_oa_pdf,
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


def test_normalize_doi() -> None:
    assert (
        normalize_doi("https://doi.org/10.1016/J.CELL.2024.01.001")
        == "10.1016/j.cell.2024.01.001"
    )
    assert normalize_doi("doi:10.1126/science.aea2535") == "10.1126/science.aea2535"
    assert normalize_doi("no doi here") is None


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
