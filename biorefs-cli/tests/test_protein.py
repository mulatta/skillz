# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from typing import cast
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from biorefs_cli.commands.protein import (
    ProteinService,
    build_search_term,
    normalize_accession,
    parse_protein_summaries,
)
from biorefs_cli.errors import CLIError, RateLimitError
from biorefs_cli.http import HttpResponse, JsonObject
from biorefs_cli.main import main


class FakeHttp:
    def __init__(
        self,
        response_text: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response_text = response_text or ""
        self.error = error
        self.urls: list[str] = []
        self.sources: list[str | None] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> HttpResponse:
        _ = headers
        self.urls.append(url)
        self.sources.append(rate_limit_source)
        if self.error is not None:
            raise self.error
        return HttpResponse(status=200, headers={}, body=self.response_text.encode())


class FakeClient:
    def __init__(
        self,
        payloads: list[dict[str, object]],
        *,
        response_text: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict[str, str | int]]] = []
        self.efetch_params: dict[str, str | int] | None = None
        self.http = FakeHttp(response_text, error)

    def request_json(self, endpoint: str, params: dict[str, str | int]) -> JsonObject:
        self.calls.append((endpoint, params))
        return cast("JsonObject", self.payloads.pop(0))

    def eutils_url(self, endpoint: str, params: dict[str, str | int]) -> str:
        self.efetch_params = params
        return f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{endpoint}.fcgi?{urlencode(params)}"

    def rate_limit_source(self, source: str = "ncbi") -> str:
        return source


def protein_summary_payload() -> dict[str, object]:
    return {
        "result": {
            "uids": ["15718680"],
            "15718680": {
                "uid": "15718680",
                "caption": "NP_000537",
                "title": "cellular tumor antigen p53 isoform a [Homo sapiens]",
                "organism": "Homo sapiens",
                "slen": "393",
                "taxid": 9606,
                "sourcedb": "refseq",
            },
        },
    }


def test_query_construction_with_taxon_filter() -> None:
    assert build_search_term("BRCA1", "9606") == "(BRCA1) AND txid9606[Organism:exp]"
    with pytest.raises(CLIError):
        build_search_term("BRCA1", "human")


def test_search_uses_esearch_taxon_filter_and_fetches_summaries() -> None:
    client = FakeClient(
        [
            {
                "esearchresult": {
                    "count": "1",
                    "idlist": ["15718680"],
                    "querytranslation": "BRCA1",
                },
            },
            protein_summary_payload(),
        ],
    )

    result = ProteinService(client).search("BRCA1", taxon="9606", limit=7)

    assert client.calls[0] == (
        "esearch",
        {
            "db": "protein",
            "term": "(BRCA1) AND txid9606[Organism:exp]",
            "retmode": "json",
            "retmax": 7,
        },
    )
    assert client.calls[1] == (
        "esummary",
        {"db": "protein", "id": "15718680", "retmode": "json"},
    )
    assert result["count"] == 1
    records = result["records"]
    assert isinstance(records, list)
    assert records[0]["accession"] == "NP_000537"


def test_esummary_parse_for_protein_result() -> None:
    records = parse_protein_summaries(protein_summary_payload())

    assert len(records) == 1
    payload = records[0].to_json_dict()
    assert payload["uid"] == "15718680"
    assert payload["accession"] == "NP_000537"
    assert payload["title"] == "cellular tumor antigen p53 isoform a [Homo sapiens]"
    assert payload["name"] == "cellular tumor antigen p53 isoform a"
    assert payload["organism"] == "Homo sapiens"
    assert payload["length"] == 393
    assert payload["source_database"] == "refseq"
    assert payload["tax_id"] == 9606


def test_fasta_passthrough_behavior() -> None:
    fasta = ">NP_009225.1 BRCA1 protein\nMELSVLLFLALLTGLLLLLVQRHP\n"
    client = FakeClient(
        [{"esearchresult": {"idlist": ["121949971"]}}],
        response_text=fasta,
    )

    result = ProteinService(client).fetch_text("np_009225.1", "fasta")

    assert result["content"] == fasta
    assert client.efetch_params == {
        "db": "protein",
        "id": "121949971",
        "retmode": "text",
        "rettype": "fasta",
    }
    assert client.http.sources == ["ncbi"]


def test_genpept_passthrough_behavior() -> None:
    genpept = "LOCUS       NP_009225                1863 aa            linear   PRI\nORIGIN\n//\n"
    client = FakeClient(
        [{"esearchresult": {"idlist": ["121949971"]}}],
        response_text=genpept,
    )

    result = ProteinService(client).fetch_text("NP_009225", "genbank")

    assert result["content"] == genpept
    assert client.efetch_params is not None
    assert client.efetch_params["rettype"] == "gp"
    assert client.efetch_params["retmode"] == "text"


def test_xml_passthrough_behavior() -> None:
    xml = '<?xml version="1.0"?><GBSet></GBSet>\n'
    client = FakeClient(
        [{"esearchresult": {"idlist": ["121949971"]}}],
        response_text=xml,
    )

    result = ProteinService(client).fetch_text("NP_009225", "xml")

    assert result["content"] == xml
    assert client.efetch_params == {
        "db": "protein",
        "id": "121949971",
        "retmode": "xml",
    }


def test_accession_validation_and_normalization() -> None:
    cases = [
        (" np_009225.1 ", "NP_009225.1"),
        ("p12345", "P12345"),
        ("WP_012345678", "WP_012345678"),
    ]
    for raw, normalized in cases:
        assert normalize_accession(raw) == normalized


def test_invalid_accessions_are_rejected() -> None:
    for raw in ["", "NP 009225", "../NP_009225", "NP__009225", "12345"]:
        with pytest.raises(CLIError):
            normalize_accession(raw)


def test_cli_argument_validation_for_format(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["protein", "fetch", "--accession", "NP_009225", "--format", "pdf"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "invalid choice" in captured.err


def test_cli_argument_validation_for_missing_accession(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(["protein", "fetch"])

    captured = capsys.readouterr()
    assert status == 2
    assert "protein fetch requires --accession" in captured.err


def test_429_handling_surfaces_rate_limited_error() -> None:
    client = FakeClient(
        [{"esearchresult": {"idlist": ["121949971"]}}],
        error=RateLimitError(),
    )

    with pytest.raises(RateLimitError):
        ProteinService(client).fetch_text("NP_009225", "fasta")


def test_json_wrapped_text_contains_content() -> None:
    fasta = ">NP_009225.1\nMELSV\n"
    client = FakeClient(
        [{"esearchresult": {"idlist": ["121949971"]}}],
        response_text=fasta,
    )

    payload = ProteinService(client).fetch_text("NP_009225", "fasta")
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)

    assert "content" in payload
    assert decoded["content"] == fasta


def test_efetch_url_contains_accession_when_esearch_cannot_resolve() -> None:
    client = FakeClient(
        [{"esearchresult": {"idlist": []}}],
        response_text=">NP_009225\nME\n",
    )

    ProteinService(client).fetch_text("NP_009225", "fasta")

    assert client.http.urls
    query = parse_qs(urlparse(client.http.urls[0]).query)
    assert query["id"] == ["NP_009225"]
