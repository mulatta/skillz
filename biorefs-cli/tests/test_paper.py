from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

import pytest
from biorefs_cli.commands.paper import (
    PaperClient,
    PaperInputError,
    cmd_convert,
    one_identifier,
    parse_jats_xml,
    parse_pubmed_xml,
)
from biorefs_cli.errors import RateLimitError
from biorefs_cli.main import main

PUBMED_XML = """
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">12345</PMID>
      <Article>
        <Journal>
          <JournalIssue>
            <Volume>12</Volume>
            <Issue>3</Issue>
            <PubDate><Year>2020</Year></PubDate>
          </JournalIssue>
          <Title>Journal of Tests</Title>
          <ISOAbbreviation>J Test</ISOAbbreviation>
        </Journal>
        <ArticleTitle>Top level identifier parsing</ArticleTitle>
        <Pagination><MedlinePgn>1-5</MedlinePgn></Pagination>
        <Abstract>
          <AbstractText Label="BACKGROUND" NlmCategory="BACKGROUND">Background text.</AbstractText>
          <AbstractText Label="RESULTS" NlmCategory="RESULTS">Result text.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author>
            <LastName>Doe</LastName>
            <ForeName>Jane</ForeName>
            <Initials>J</Initials>
            <AffiliationInfo><Affiliation>Example University</Affiliation></AffiliationInfo>
          </Author>
        </AuthorList>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
        </PublicationTypeList>
        <GrantList>
          <Grant><GrantID>R01</GrantID><Agency>NIH</Agency><Country>US</Country></Grant>
        </GrantList>
      </Article>
      <MeshHeadingList>
        <MeshHeading>
          <DescriptorName MajorTopicYN="Y">Genes</DescriptorName>
        </MeshHeading>
      </MeshHeadingList>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">12345</ArticleId>
        <ArticleId IdType="doi">10.1000/Test.DOI</ArticleId>
        <ArticleId IdType="pmc">PMC123456</ArticleId>
      </ArticleIdList>
      <ReferenceList>
        <Reference>
          <ArticleIdList>
            <ArticleId IdType="pubmed">99999</ArticleId>
            <ArticleId IdType="doi">10.1000/reference</ArticleId>
          </ArticleIdList>
        </Reference>
      </ReferenceList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

JATS_XML = """
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front>
    <article-meta>
      <article-id pub-id-type="pmid">12345</article-id>
      <article-id pub-id-type="pmc">123456</article-id>
      <article-id pub-id-type="doi">10.1000/test.doi</article-id>
      <permissions>
        <license license-type="cc-by" xlink:href="https://creativecommons.org/licenses/by/4.0/" />
      </permissions>
      <abstract><p>Abstract text.</p></abstract>
    </article-meta>
  </front>
  <body>
    <sec><title>Methods</title><p>Methods paragraph.</p></sec>
    <sec>
      <title>Results</title>
      <p>Results paragraph.</p>
      <sec><title>Secondary analysis</title><p>Nested result.</p></sec>
    </sec>
  </body>
  <back>
    <ref-list>
      <ref>
        <label>1</label>
        <mixed-citation>Reference text <pub-id pub-id-type="pmid">222</pub-id></mixed-citation>
      </ref>
    </ref-list>
  </back>
  <fig><label>Figure 1</label><caption><p>Figure caption.</p></caption></fig>
  <table-wrap><label>Table 1</label><caption><p>Table caption.</p></caption></table-wrap>
</article>
"""


class RateLimitedConvertClient:
    def id_convert(self, _kind: str, _value: str) -> dict[str, Any]:
        raise RateLimitError(retry_after_seconds=7.0)


def test_pubmed_xml_uses_only_top_level_article_ids() -> None:
    records = parse_pubmed_xml(
        PUBMED_XML, {"abstract", "authors", "mesh", "grants", "ids"}
    )

    record = records[0]

    assert record["identifiers"] == {
        "pmid": "12345",
        "doi": "10.1000/test.doi",
        "pmcid": "PMC123456",
    }
    assert "99999" not in str(record["identifiers"])
    assert "reference" not in str(record["identifiers"])
    assert record["abstract"]["text"] == "Background text.\nResult text."
    assert record["authors"][0]["affiliations"] == ["Example University"]
    assert record["mesh"][0]["descriptor"] == "Genes"
    assert record["grants"][0]["id"] == "R01"


def test_pmc_jats_extracts_sections_tables_figures_and_references() -> None:
    record = parse_jats_xml(JATS_XML, {"methods", "results"})

    fulltext = record["fulltext"]

    assert fulltext["status"] == "full-text"
    assert record["identifiers"]["pmcid"] == "PMC123456"
    assert [section["type"] for section in fulltext["sections"]] == [
        "methods",
        "results",
        "results",
    ]
    assert fulltext["figures"][0]["caption"] == "Figure caption."
    assert fulltext["tables"][0]["caption"] == "Table caption."
    assert fulltext["references"][0]["identifiers"]["pmid"] == "222"


def test_one_identifier_requires_exactly_one_identifier() -> None:
    assert one_identifier("123", None, None) == ("pmid", "123")
    assert one_identifier(None, "123456", None) == ("pmcid", "PMC123456")
    assert one_identifier(None, None, "https://doi.org/10.1000/Example") == (
        "doi",
        "10.1000/example",
    )
    with pytest.raises(PaperInputError):
        one_identifier(None, None, None)
    with pytest.raises(PaperInputError):
        one_identifier("123", None, "10.1000/example")


def test_cli_identifier_validation_fails_before_network(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(
        ["paper", "fetch", "--pmid", "123", "--doi", "10.1000/example", "--json"]
    )

    captured = capsys.readouterr()

    assert status == 2
    assert "provide exactly one identifier" in captured.err


def test_429_convert_returns_structured_rate_limited_status() -> None:
    args = argparse.Namespace(pmid="123", pmcid=None, doi=None)

    result = cmd_convert(cast("PaperClient", RateLimitedConvertClient()), args)

    assert result["status"] == "rate-limited"
    assert result["error"] == "rate-limited"
    assert result["retry_after_seconds"] == 7.0
    assert result["input"] == {"pmid": "123"}


def test_pubmed_search_uses_stable_json_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePaperClient(PaperClient):
        def __init__(self) -> None:
            pass

        def esearch_pubmed(
            self,
            query: str,
            *,
            limit: int,
            since: str | None,
            until: str | None,
        ) -> dict[str, Any]:
            assert query == "(BRCA1) AND (review[Publication Type])"
            assert limit == 1
            assert since == "2020"
            assert until == "2024"
            return {
                "esearchresult": {
                    "count": "1",
                    "idlist": ["12345"],
                    "querytranslation": "BRCA1 AND review[Publication Type]",
                }
            }

        def efetch_pubmed(self, pmids: Sequence[str]) -> str:
            assert list(pmids) == ["12345"]
            return PUBMED_XML

    monkeypatch.setattr("biorefs_cli.commands.paper.load_config", lambda: None)
    monkeypatch.setattr(
        "biorefs_cli.commands.paper.PaperClient", lambda _config: FakePaperClient()
    )

    status = main(
        [
            "paper",
            "search",
            "BRCA1",
            "--source",
            "pubmed",
            "--type",
            "review",
            "--since",
            "2020",
            "--until",
            "2024",
            "--limit",
            "1",
            "--json",
        ]
    )

    assert status == 0
