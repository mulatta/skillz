# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Nucleotide command tests."""

from __future__ import annotations

import json
from typing import cast
from urllib.parse import parse_qs, urlparse

import pytest
from biorefs_cli.commands import nucleotide
from biorefs_cli.config import Config
from biorefs_cli.errors import CLIError, RateLimitError
from biorefs_cli.http import HttpClient, HttpResponse, JsonObject
from biorefs_cli.main import build_parser, main
from biorefs_cli.ncbi_client import NCBIClient


class FakeHttpClient(HttpClient):
    def __init__(
        self, json_payloads: list[dict[str, object]], text_payloads: list[str]
    ) -> None:
        self.json_payloads = json_payloads
        self.text_payloads = text_payloads
        self.json_urls: list[str] = []
        self.text_urls: list[str] = []
        self.rate_limit_sources: list[str | None] = []

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> JsonObject:
        _ = headers
        self.json_urls.append(url)
        self.rate_limit_sources.append(rate_limit_source)
        if not self.json_payloads:
            raise AssertionError
        return cast("JsonObject", self.json_payloads.pop(0))

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> HttpResponse:
        _ = headers
        self.text_urls.append(url)
        self.rate_limit_sources.append(rate_limit_source)
        if not self.text_payloads:
            raise AssertionError
        return HttpResponse(200, {}, self.text_payloads.pop(0).encode())


class RateLimitedHttpClient(HttpClient):
    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> JsonObject:
        _ = (url, headers, rate_limit_source)
        raise RateLimitError


def make_client(http: HttpClient) -> NCBIClient:
    return NCBIClient(Config(email="researcher@example.org"), http)


def params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def summary_payload() -> dict[str, object]:
    return {
        "result": {
            "uids": ["555"],
            "555": {
                "uid": "555",
                "caption": "NM_007294",
                "accessionversion": "NM_007294.4",
                "title": "Homo sapiens BRCA1 DNA repair associated (BRCA1), mRNA",
                "organism": "Homo sapiens",
                "biomol": "mRNA",
                "slen": 7088,
                "gi": 1519311452,
                "sourcedb": "refseq",
            },
        },
    }


def test_query_construction_for_taxon_kind_and_refseq_filters() -> None:
    mrna = nucleotide.build_nucleotide_query("BRCA1", taxon="9606", kind="mrna")
    assert "(BRCA1)" in mrna
    assert "txid9606[Organism:exp]" in mrna
    assert "mRNA[Filter]" in mrna

    refseq = nucleotide.build_nucleotide_query("BRCA1", taxon=None, kind="refseq")
    assert "srcdb_refseq[PROP]" in refseq

    genomic = nucleotide.build_nucleotide_query(
        "mitochondrion", taxon="9606", kind="genomic"
    )
    assert "biomol_genomic[PROP]" in genomic

    lncrna = nucleotide.build_nucleotide_query("HOTAIR", taxon=None, kind="lncrna")
    assert "lncRNA[Title]" in lncrna


def test_esummary_parse_for_nucleotide_result() -> None:
    records = nucleotide.parse_nucleotide_summaries(summary_payload())

    assert records == [
        {
            "source": "ncbi",
            "source_db": "nuccore",
            "uid": "555",
            "gi": "1519311452",
            "accession": "NM_007294.4",
            "title": "Homo sapiens BRCA1 DNA repair associated (BRCA1), mRNA",
            "organism": "Homo sapiens",
            "molecule_type": "mRNA",
            "length": 7088,
            "provenance": {"endpoint": "esummary", "database": "nuccore"},
        }
    ]


def test_search_uses_esearch_and_esummary_with_filters() -> None:
    http = FakeHttpClient(
        [
            {
                "esearchresult": {
                    "idlist": ["555"],
                    "count": "1",
                    "querytranslation": "BRCA1",
                }
            },
            summary_payload(),
        ],
        [],
    )
    client = make_client(http)

    result = nucleotide.search_nucleotide(
        client, query="BRCA1", taxon="9606", kind="refseq", limit=5
    )

    search_params = params(http.json_urls[0])
    summary_params = params(http.json_urls[1])
    assert search_params["db"] == ["nuccore"]
    assert search_params["retmax"] == ["5"]
    assert "txid9606[Organism:exp]" in search_params["term"][0]
    assert "srcdb_refseq[PROP]" in search_params["term"][0]
    assert summary_params["id"] == ["555"]
    assert http.rate_limit_sources == ["ncbi", "ncbi"]
    assert result["records"][0]["accession"] == "NM_007294.4"


def test_fasta_and_genbank_passthrough_behavior() -> None:
    http = FakeHttpClient(
        [
            {"esearchresult": {"idlist": ["555"], "count": "1"}},
            {"esearchresult": {"idlist": ["555"], "count": "1"}},
        ],
        [">NM_007294.4 BRCA1\nACGT\n", "LOCUS       NM_007294\nORIGIN\n//\n"],
    )
    client = make_client(http)

    fasta = nucleotide.fetch_nucleotide_text(
        client, accession="nm_007294.4", fetch_format="fasta"
    )
    genbank = nucleotide.fetch_nucleotide_text(
        client, accession="NM_007294.4", fetch_format="genbank"
    )

    assert fasta["content"] == ">NM_007294.4 BRCA1\nACGT\n"
    assert genbank["content"].startswith("LOCUS")
    assert params(http.text_urls[0])["rettype"] == ["fasta"]
    assert params(http.text_urls[1])["rettype"] == ["gb"]
    assert http.rate_limit_sources == ["ncbi", "ncbi", "ncbi", "ncbi"]


def test_xml_passthrough_behavior() -> None:
    http = FakeHttpClient(
        [{"esearchresult": {"idlist": ["555"], "count": "1"}}],
        ["<GBSet><GBSeq /></GBSet>\n"],
    )
    client = make_client(http)

    xml = nucleotide.fetch_nucleotide_text(
        client, accession="NM_007294.4", fetch_format="xml"
    )

    xml_params = params(http.text_urls[0])
    assert xml["content"] == "<GBSet><GBSeq /></GBSet>\n"
    assert "rettype" not in xml_params
    assert xml_params["retmode"] == ["xml"]


def test_accession_validation_and_normalization() -> None:
    assert nucleotide.normalize_accession(" nm_007294.4 ") == "NM_007294.4"
    assert nucleotide.accession_query("nc_000001.11") == "NC_000001.11[Accession]"
    with pytest.raises(CLIError):
        nucleotide.normalize_accession("not an accession")


def test_cli_argument_validation(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "nucleotide",
            "search",
            "BRCA1",
            "--taxon",
            "9606",
            "--kind",
            "refseq",
            "--limit",
            "5",
            "--json",
        ]
    )
    assert args.command == "nucleotide"
    assert args.nucleotide_command == "search"
    assert args.limit == 5

    with pytest.raises(SystemExit):
        parser.parse_args(["nucleotide", "search", "BRCA1", "--kind", "bad"])

    assert main(["nucleotide", "fetch"]) == 2
    assert "nucleotide fetch requires --accession" in capsys.readouterr().err

    with pytest.raises(CLIError):
        nucleotide.validate_limit(0)


def test_fetch_summary_and_json_formats_return_parsed_summary() -> None:
    http = FakeHttpClient(
        [
            {"esearchresult": {"idlist": ["555"], "count": "1"}},
            summary_payload(),
        ],
        [],
    )
    client = make_client(http)

    summary = nucleotide.fetch_nucleotide_summary(client, "NM_007294")

    assert summary["uid"] == "555"
    assert summary["accession"] == "NM_007294.4"


def test_429_handling_surfaces_rate_limited_error() -> None:
    client = make_client(RateLimitedHttpClient(timeout_seconds=3))

    with pytest.raises(RateLimitError):
        nucleotide.search_nucleotide(
            client, query="BRCA1", taxon=None, kind=None, limit=1
        )


def test_cli_prints_json_when_requested(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    http = FakeHttpClient(
        [
            {"esearchresult": {"idlist": ["555"], "count": "1"}},
            summary_payload(),
        ],
        [],
    )
    client = make_client(http)
    monkeypatch.setattr(nucleotide, "build_client", lambda: client)

    status = main(["nucleotide", "search", "BRCA1", "--limit", "1", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert status == 0
    assert payload["records"][0]["uid"] == "555"
