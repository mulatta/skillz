# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, cast

import pytest
from biorefs_cli.commands import openalex
from biorefs_cli.config import Config
from biorefs_cli.http import HttpClient

if TYPE_CHECKING:
    from biorefs_cli.http import JsonObject


WORK_FIXTURE: JsonObject = {
    "id": "https://openalex.org/W2741809807",
    "doi": "https://doi.org/10.7717/peerj.4375",
    "ids": {
        "openalex": "https://openalex.org/W2741809807",
        "doi": "https://doi.org/10.7717/peerj.4375",
        "pmid": "https://pubmed.ncbi.nlm.nih.gov/29456894",
        "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5828010/",
    },
    "title": "A biomedical example work",
    "publication_year": 2018,
    "publication_date": "2018-02-13",
    "authorships": [
        {
            "author_position": "first",
            "is_corresponding": True,
            "author": {
                "id": "https://openalex.org/A1",
                "display_name": "Ada Lovelace",
                "orcid": "https://orcid.org/0000-0001-0000-0000",
            },
            "institutions": [
                {
                    "id": "https://openalex.org/I1",
                    "display_name": "Example Institute",
                    "ror": "https://ror.org/12345",
                    "country_code": "US",
                }
            ],
        }
    ],
    "primary_location": {
        "source": {
            "id": "https://openalex.org/S1",
            "display_name": "PeerJ",
            "issn_l": "2167-8359",
            "issn": ["2167-8359"],
            "type": "journal",
            "is_oa": True,
            "is_in_doaj": True,
        }
    },
    "open_access": {
        "is_oa": True,
        "oa_status": "gold",
        "oa_url": "https://example.org/article",
        "any_repository_has_fulltext": False,
    },
    "best_oa_location": {
        "is_oa": True,
        "landing_page_url": "https://example.org/article",
        "pdf_url": "https://example.org/article.pdf",
        "license": "cc-by",
        "license_id": "cc-by",
        "version": "publishedVersion",
        "source": {"display_name": "PeerJ", "type": "journal"},
    },
    "locations": [
        {
            "is_oa": True,
            "landing_page_url": "https://example.org/article",
            "pdf_url": "https://example.org/article.pdf",
            "license": "cc-by",
            "version": "publishedVersion",
            "source": {"display_name": "PeerJ", "type": "journal"},
        }
    ],
    "referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"],
    "referenced_works_count": 2,
    "cited_by_count": 10,
    "related_works": ["https://openalex.org/W3"],
    "topics": [
        {
            "id": "https://openalex.org/T1",
            "display_name": "Bioinformatics",
            "score": 0.9,
        }
    ],
    "concepts": [
        {
            "id": "https://openalex.org/C1",
            "display_name": "Biology",
            "level": 0,
            "score": 0.8,
        }
    ],
    "is_retracted": False,
    "is_paratext": False,
}

OA_MISSING_PDF_FIXTURE: JsonObject = {
    **WORK_FIXTURE,
    "best_oa_location": {
        "is_oa": True,
        "landing_page_url": "https://repository.example/work",
        "pdf_url": None,
        "license": "cc-by-nc",
        "version": "acceptedVersion",
        "source": {"display_name": "Repository", "type": "repository"},
    },
    "locations": [
        {
            "is_oa": True,
            "landing_page_url": "https://repository.example/work",
            "pdf_url": None,
            "license": "cc-by-nc",
            "version": "acceptedVersion",
            "source": {"display_name": "Repository", "type": "repository"},
        }
    ],
}

REFERENCE_FIXTURE: JsonObject = {
    "id": "https://openalex.org/W1",
    "ids": {"openalex": "https://openalex.org/W1"},
    "display_name": "Referenced work",
    "publication_year": 2017,
    "open_access": {"is_oa": False, "oa_status": "closed"},
}

TRENDS_FIXTURE: JsonObject = {
    "group_by": [
        {"key": "2024", "key_display_name": "2024", "count": 12},
        {"key": "2023", "key_display_name": "2023", "count": 8},
    ]
}


class RecordingHttpClient(HttpClient):
    def __init__(self) -> None:
        super().__init__(timeout_seconds=3)
        self.urls: list[str] = []
        self.rate_limit_sources: list[str | None] = []

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> JsonObject:
        assert headers is not None
        self.urls.append(url)
        self.rate_limit_sources.append(rate_limit_source)
        return WORK_FIXTURE


class FakeOpenAlexClient(openalex.OpenAlexClient):
    def __init__(self) -> None:
        super().__init__(config=Config())

    def get_work(self, request_id: str, _select: str) -> openalex.OpenAlexResponse:
        if request_id == "W1":
            return openalex.OpenAlexResponse(
                REFERENCE_FIXTURE, "https://api.openalex.org/works/W1"
            )
        return openalex.OpenAlexResponse(
            WORK_FIXTURE, "https://api.openalex.org/works/W2741809807"
        )

    def list_works(self, params: dict[str, str]) -> openalex.OpenAlexResponse:
        assert params["filter"] == "cites:W2741809807"
        return openalex.OpenAlexResponse(
            {"results": [REFERENCE_FIXTURE], "meta": {"count": 1}},
            "https://api.openalex.org/works?filter=cites:W2741809807",
        )


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    openalex.register(subparsers)
    return parser.parse_args(["openalex", *argv])


def test_identifier_normalization() -> None:
    doi = openalex.normalize_work_identifier(
        "doi", "https://doi.org/10.1158/2159-8290.CD-12-0049"
    )
    assert doi.request_id == "doi:10.1158/2159-8290.cd-12-0049"

    pmid = openalex.normalize_work_identifier(
        "pmid", "https://pubmed.ncbi.nlm.nih.gov/23103855/"
    )
    assert pmid.request_id == "pmid:23103855"

    pmcid = openalex.normalize_work_identifier("pmcid", "pmcid:pmc3525065")
    assert pmcid.request_id == "pmcid:PMC3525065"

    work = openalex.normalize_work_identifier(
        "openalex", "https://openalex.org/W2741809807"
    )
    assert work.request_id == "W2741809807"


def test_client_uses_mailto_and_openalex_rate_limit_source() -> None:
    http = RecordingHttpClient()
    client = openalex.OpenAlexClient(config=Config(email="user@example.org"), http=http)

    client.get_work("doi:10.7717/peerj.4375", openalex.WORK_SELECT)

    assert "mailto=user%40example.org" in http.urls[0]
    assert "works/doi:10.7717%2Fpeerj.4375" in http.urls[0]
    assert http.rate_limit_sources == ["openalex"]


def as_json_object(value: object) -> JsonObject:
    assert isinstance(value, dict)
    return cast("JsonObject", value)


def as_json_object_list(value: object) -> list[JsonObject]:
    assert isinstance(value, list)
    for item in value:
        assert isinstance(item, dict)
    return cast("list[JsonObject]", value)


def test_work_parse() -> None:
    identifier = openalex.normalize_work_identifier("doi", "10.7717/peerj.4375")
    response = openalex.OpenAlexResponse(
        WORK_FIXTURE, "https://api.openalex.org/works/W2741809807"
    )

    result = openalex.parse_work_result(response, identifier)

    work = as_json_object(result["work"])
    assert result["identifiers"] == work["identifiers"]
    assert work["title"] == "A biomedical example work"
    assert work["doi"] == "10.7717/peerj.4375"
    assert work["pmid"] == "29456894"
    assert work["pmcid"] == "PMC5828010"
    assert work["referenced_works_count"] == 2
    assert work["cited_by_count"] == 10
    authors = as_json_object_list(work["authors"])
    assert authors[0]["name"] == "Ada Lovelace"


def test_oa_location_parse_missing_pdf_url() -> None:
    identifier = openalex.normalize_work_identifier("pmid", "29456894")
    response = openalex.OpenAlexResponse(
        OA_MISSING_PDF_FIXTURE, "https://api.openalex.org/works/W2741809807"
    )

    result = openalex.parse_oa_result(response, identifier)

    locations = as_json_object_list(result["locations"])
    assert len(locations) == 1
    assert locations[0]["url_type"] == "landing-page"
    assert locations[0]["url"] == "https://repository.example/work"
    best = as_json_object(result["best_oa_location"])
    assert best["url_type"] == "landing-page"


def test_graph_references_response_parse() -> None:
    args = parse(
        [
            "graph",
            "--openalex-id",
            "W2741809807",
            "--direction",
            "references",
            "--limit",
            "1",
        ]
    )

    result = openalex.run(args, FakeOpenAlexClient())

    edges = as_json_object_list(result["edges"])
    nodes = as_json_object_list(result["nodes"])
    assert result["truncated"] is True
    assert edges[0]["source"] == "W2741809807"
    assert edges[0]["target"] == "W1"
    assert nodes[1]["title"] == "Referenced work"


def test_graph_cited_by_response_parse() -> None:
    args = parse(
        [
            "graph",
            "--openalex-id",
            "W2741809807",
            "--direction",
            "cited-by",
            "--limit",
            "5",
        ]
    )

    result = openalex.run(args, FakeOpenAlexClient())

    edges = as_json_object_list(result["edges"])
    assert edges[0]["source"] == "W1"
    assert edges[0]["target"] == "W2741809807"
    assert edges[0]["provenance"] == "openalex.filter.cites"


def test_trends_group_by_parse() -> None:
    response = openalex.OpenAlexResponse(
        TRENDS_FIXTURE, "https://api.openalex.org/works?group_by=publication_year"
    )
    context = openalex.TrendContext(
        query="spatial transcriptomics",
        group_by="publication-year",
        openalex_group_by="publication_year",
        filter_value="type:article,publication_year:>2019",
    )

    result = openalex.parse_trends_response(response, context)

    rows = as_json_object_list(result["rows"])
    assert rows[0]["key"] == "2024"
    assert rows[0]["count"] == 12
    assert result["openalex_group_by"] == "publication_year"


def test_cli_argument_validation_requires_exactly_one_identifier() -> None:
    too_many = parse(
        [
            "work",
            "--doi",
            "10.7717/peerj.4375",
            "--pmid",
            "29456894",
        ]
    )
    with pytest.raises(ValueError, match="exactly one"):
        openalex.run(too_many, FakeOpenAlexClient())

    missing = parse(["oa"])
    with pytest.raises(ValueError, match="exactly one"):
        openalex.run(missing, FakeOpenAlexClient())


def test_cli_argument_validation_for_graph_limit_and_trends_range() -> None:
    bad_limit = parse(
        [
            "graph",
            "--doi",
            "10.7717/peerj.4375",
            "--direction",
            "related",
            "--limit",
            "0",
        ]
    )
    with pytest.raises(ValueError, match="limit"):
        openalex.run(bad_limit, FakeOpenAlexClient())

    bad_range = parse(
        [
            "trends",
            "BRCA1",
            "--group-by",
            "oa-status",
            "--since",
            "2024",
            "--until",
            "2020",
        ]
    )
    with pytest.raises(ValueError, match="since"):
        openalex.run(bad_range, FakeOpenAlexClient())
