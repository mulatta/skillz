# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
from typing import Any, cast

import pytest

from biorefs_cli.commands.paper import (
    PaperClient,
    PaperInputError,
    bibtex,
    cmd_cite,
    cmd_fulltext,
    cmd_related,
    crossref_year,
    europepmc_unavailable,
    fetch_record,
    format_citation,
    normalize_crossref_work,
    normalize_doi,
    normalize_idconv,
    normalize_identifier,
    normalize_pmcid,
    normalize_pmid,
    parse_include,
    parse_jats_xml,
    parse_sections,
    print_convert,
    print_fetch,
    print_fulltext,
    print_related,
    print_search,
    ris,
    source_urls,
    strict_validate,
    unavailable,
)
from biorefs_cli.errors import HTTPError

MINIMAL_PUBMED_XML = """
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>123</PMID>
      <Article>
        <Journal>
          <JournalIssue><PubDate><MedlineDate>2021 Jan-Feb</MedlineDate></PubDate></JournalIssue>
          <Title>Journal Title</Title>
        </Journal>
        <ArticleTitle>Resolved title</ArticleTitle>
        <AuthorList><Author><LastName>Smith</LastName><ForeName>Ada</ForeName></Author></AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/example</ArticleId></ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

ABSTRACT_ONLY_JATS = """
<article>
  <front><article-meta><article-id pub-id-type="pmc">42</article-id><abstract><p>Only abstract.</p></abstract></article-meta></front>
</article>
"""

SAMPLE_RECORD = {
    "identifiers": {"doi": "10.1000/example", "pmid": "123", "pmcid": "PMC42"},
    "title": "Example title",
    "year": "2024",
    "journal": {"title": "Example Journal"},
    "authors": [
        {"family": "Smith", "given": "Ada", "collective": None},
        {"family": "Jones", "given": "Grace", "collective": None},
        {"family": "Brown", "given": "Lin", "collective": None},
        {"family": "Miller", "given": "Pat", "collective": None},
    ],
}


class ResolvingClient:
    def resolve_pmid(
        self,
        kind: str,
        value: str,
    ) -> tuple[str | None, list[str], dict[str, Any] | None]:
        if value == "missing":
            return (
                None,
                ["not-found"],
                {"identifiers": {kind: value, "doi": "10.1000/missing"}},
            )
        if value == "warn":
            return "123", ["fallback-used"], {"identifiers": {"pmid": "123"}}
        return "123", [], None

    def efetch_pubmed(self, pmids: list[str]) -> str:
        assert pmids == ["123"]
        return MINIMAL_PUBMED_XML


class FulltextNoPmcidClient:
    def id_convert(self, kind: str, value: str) -> dict[str, Any]:
        assert (kind, value) == ("doi", "10.1000/missing")
        return {"status": "unresolved", "identifiers": {"doi": value}}

    def resolve_pmid(
        self,
        kind: str,
        value: str,
    ) -> tuple[str | None, list[str], dict[str, Any] | None]:
        assert (kind, value) == ("doi", "10.1000/missing")
        return None, ["doi-not-found-in-pubmed"], None


class FulltextPmcClient:
    def efetch_pmc(self, pmcid: str) -> str:
        assert pmcid == "PMC42"
        return ABSTRACT_ONLY_JATS


class RelatedClient:
    def elink_pubmed(self, pmid: str, *, mode: str) -> dict[str, Any]:
        assert (pmid, mode) == ("123", "similar")
        return {"linksets": [{"linksetdbs": [{"links": ["456", "abc", "789"]}]}]}

    def efetch_pubmed(self, pmids: list[str]) -> str:
        assert pmids == ["456"]
        return MINIMAL_PUBMED_XML


class CiteClient(ResolvingClient):
    def __init__(self, *, export: str | None = None, fail_export: bool = False) -> None:
        self.export = export
        self.fail_export = fail_export

    def crossref_work(self, doi: str) -> dict[str, Any]:
        assert doi == "10.1000/missing"
        return SAMPLE_RECORD | {"identifiers": {"doi": doi}}

    def crossref_export(self, doi: str, accept: str) -> str | None:
        assert doi == "10.1000/example"
        assert accept == "application/x-bibtex"
        if self.fail_export:
            msg = "crossref failed"
            raise HTTPError(msg)
        return self.export


def ns(**kwargs: object) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_fetch_record_unresolved_and_warning_paths() -> None:
    unresolved = fetch_record(
        cast("PaperClient", ResolvingClient()),
        "doi",
        "missing",
        {"ids"},
    )
    warned = fetch_record(
        cast("PaperClient", ResolvingClient()),
        "doi",
        "warn",
        {"ids"},
    )

    assert unresolved["status"] == "unresolved"
    assert unresolved["warnings"] == ["not-found"]
    assert warned["warnings"] == ["fallback-used"]
    assert warned["title"] == "Resolved title"


def test_fulltext_unavailable_paths() -> None:
    europe = cmd_fulltext(
        cast("PaperClient", FulltextNoPmcidClient()),
        ns(
            pmid=None,
            pmcid=None,
            doi="10.1000/missing",
            sections=None,
            source="europepmc",
        ),
    )
    no_pmcid = cmd_fulltext(
        cast("PaperClient", FulltextNoPmcidClient()),
        ns(pmid=None, pmcid=None, doi="10.1000/missing", sections=None, source="auto"),
    )
    abstract_only = cmd_fulltext(
        cast("PaperClient", FulltextPmcClient()),
        ns(pmid=None, pmcid="PMC42", doi=None, sections="methods", source="auto"),
    )

    assert europe["fulltext"]["reason"] == "europepmc-fulltextxml-not-implemented"
    assert no_pmcid["fulltext"]["reason"] == "no-pmcid"
    assert abstract_only["fulltext"]["status"] == "abstract-only"


def test_related_supported_and_unsupported_paths() -> None:
    supported = cmd_related(
        cast("PaperClient", RelatedClient()),
        ns(pmid="123", doi=None, mode="similar", limit=1),
    )
    unsupported = cmd_related(
        cast("PaperClient", RelatedClient()),
        ns(pmid=None, doi="10.1000/example", mode="cited-by", limit=1),
    )

    assert supported["ids"] == ["456"]
    assert supported["records"][0]["identifiers"]["pmid"] == "123"
    assert unsupported["status"] == "unsupported"


def test_cite_crossref_export_fallback_and_strict_validation() -> None:
    exported = cmd_cite(
        cast("PaperClient", CiteClient(export="@article{example}")),
        ns(pmid=None, pmcid=None, doi="10.1000/example", format="bibtex", strict=True),
    )
    fallback = cmd_cite(
        cast("PaperClient", CiteClient(fail_export=True)),
        ns(pmid=None, pmcid=None, doi="10.1000/example", format="bibtex", strict=True),
    )

    assert exported == "@article{example}"
    assert fallback.startswith("@article{")
    with pytest.raises(PaperInputError, match="missing core citation fields"):
        strict_validate({"identifiers": {"doi": "10.1000/example"}})


def test_citation_formatters_cover_markdown_bibtex_ris_json() -> None:
    assert "Example title" in format_citation(SAMPLE_RECORD, "markdown")
    assert "Smith, Ada" in bibtex(SAMPLE_RECORD)
    assert "AU  - Smith, Ada" in ris(SAMPLE_RECORD)
    assert '"title": "Example title"' in format_citation(SAMPLE_RECORD, "json")
    with pytest.raises(PaperInputError):
        format_citation(SAMPLE_RECORD, "unknown")


def test_crossref_and_idconv_normalizers_cover_missing_fields() -> None:
    work = normalize_crossref_work(
        {
            "DOI": "10.1000/Example",
            "title": ["Crossref title"],
            "container-title": ["Journal"],
            "short-container-title": ["J"],
            "author": [{"family": "Doe", "given": "Jane"}],
            "issued": {"date-parts": [[2024, 1, 2]]},
            "publisher": "Publisher",
            "URL": "https://doi.org/10.1000/example",
        },
    )
    unresolved = normalize_idconv("10.1000/missing", {"records": []})
    no_pmcid = normalize_idconv("123", {"records": [{"pmid": "123", "status": "ok"}]})

    assert work["year"] == "2024"
    assert crossref_year({"issued": {"date-parts": [["bad"]]}}) is None
    assert unresolved["warnings"] == ["pmc-id-converter:no-record"]
    assert no_pmcid["warnings"] == ["no-pmcid"]


def test_parse_helpers_and_invalid_inputs() -> None:
    assert parse_include("") == {"abstract", "authors", "ids"}
    assert parse_sections("methods, results") == {"methods", "results"}
    assert parse_sections(None) is None
    assert source_urls({"pmid": "1", "pmcid": "PMC2", "doi": "10.1000/example"}) == {
        "pubmed": "https://pubmed.ncbi.nlm.nih.gov/1/",
        "pmc": "https://pmc.ncbi.nlm.nih.gov/articles/PMC2/",
        "doi": "https://doi.org/10.1000/example",
    }
    assert parse_jats_xml("", None)["fulltext"]["reason"] == "pmc:empty-response"
    assert parse_jats_xml("<root />", None)["fulltext"]["reason"] == "pmc:no-article"
    assert unavailable("why")["fulltext"]["reason"] == "why"
    assert europepmc_unavailable("pmid", "1")["evidence_level"] == "unavailable"

    for kind, value in (
        ("pmid", "abc"),
        ("pmcid", "bad"),
        ("doi", "not-a-doi"),
        ("bad", "1"),
    ):
        with pytest.raises(PaperInputError):
            normalize_identifier(kind, value)
    with pytest.raises(PaperInputError):
        parse_include("abstract,unknown")
    with pytest.raises(PaperInputError):
        normalize_pmid("abc")
    with pytest.raises(PaperInputError):
        normalize_pmcid("PMCabc")
    with pytest.raises(PaperInputError):
        normalize_doi("https://example.org/not-doi")


def test_human_printers_cover_markdown_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    search = {"count": 1, "ids": ["123"], "records": [SAMPLE_RECORD]}
    fulltext = {
        "fulltext": {
            "status": "full-text",
            "sections": [{"title": "Methods", "text": "Body"}],
        },
    }
    unsupported_related = {"status": "unsupported", "reason": "not now"}
    related = {"records": [SAMPLE_RECORD]}

    print_search(search)
    print_fetch(SAMPLE_RECORD | {"abstract": {"text": "Abstract"}})
    print_convert(
        {"status": "resolved", "identifiers": {"pmid": "123"}, "warnings": ["warn"]},
    )
    print_fulltext(fulltext)
    print_related(unsupported_related)
    print_related(related)

    captured = capsys.readouterr().out
    assert "PubMed search" in captured
    assert "Abstract" in captured
    assert "Warnings: warn" in captured
    assert "Methods" in captured
    assert "Unsupported: not now" in captured
    assert "Example title" in captured
