from __future__ import annotations

import json
from typing import cast
from urllib.parse import parse_qs, urlparse

import pytest
from biorefs_cli.commands import gene
from biorefs_cli.config import Config
from biorefs_cli.errors import CLIError, RateLimitError
from biorefs_cli.http import HttpClient, HttpResponse, JsonObject, RetryPolicy
from biorefs_cli.main import build_parser, main
from biorefs_cli.ncbi_client import NCBIClient
from biorefs_cli.rate_limit import RateLimiter

GENE_SUMMARY: JsonObject = {
    "result": {
        "uids": ["672"],
        "672": {
            "uid": "672",
            "name": "BRCA1",
            "description": "BRCA1 DNA repair associated",
            "nomenclaturesymbol": "BRCA1",
            "nomenclaturename": "BRCA1 DNA repair associated",
            "otheraliases": "BRCC1, FANCS, RNF53",
            "maplocation": "17q21.31",
            "summary": "This gene maintains genomic stability.",
            "organism": {
                "scientificname": "Homo sapiens",
                "commonname": "human",
                "taxid": 9606,
            },
        },
    }
}

ELINK: JsonObject = {
    "linksets": [
        {
            "dbfrom": "gene",
            "ids": ["672"],
            "linksetdbs": [
                {"dbto": "pubmed", "linkname": "gene_pubmed", "links": ["1", "2"]},
                {"dbto": "protein", "linkname": "gene_protein_refseq", "links": ["10"]},
                {
                    "dbto": "nuccore",
                    "linkname": "gene_nuccore_refseqrna",
                    "links": ["20"],
                },
            ],
        }
    ]
}


def test_taxon_alias_parsing() -> None:
    assert gene.parse_taxon("human") == "9606"
    assert gene.parse_taxon("mouse") == "10090"
    assert gene.parse_taxon("9606") == "9606"
    with pytest.raises(CLIError, match="taxon"):
        gene.parse_taxon("rat")


def test_esummary_parse_gene_record() -> None:
    records = gene.parse_gene_summaries(GENE_SUMMARY)

    assert records[0]["identifiers"] == {"gene_id": "672", "tax_id": "9606"}
    assert records[0]["official_symbol"] == "BRCA1"
    assert records[0]["aliases"] == ["BRCC1", "FANCS", "RNF53"]
    assert records[0]["map_location"] == "17q21.31"


def test_elink_parse_pubmed_protein_nucleotide_links() -> None:
    links = gene.parse_elink(ELINK, source_db="gene", requested_target_db="pubmed")

    by_db = {(link["target_db"], link["target_id"]) for link in links}
    assert ("pubmed", "1") in by_db
    assert ("protein", "10") in by_db
    assert ("nuccore", "20") in by_db


def test_ambiguous_symbol_resolution_outputs_candidates() -> None:
    client = FakeGeneClient(
        records=[
            {"gene_id": "1", "official_symbol": "ABC1", "description": "first"},
            {"gene_id": "2", "official_symbol": "ABC1", "description": "second"},
        ]
    )

    with pytest.raises(gene.AmbiguousGeneError) as excinfo:
        gene.resolve_symbol(client, "ABC1", "human")

    assert [candidate["gene_id"] for candidate in excinfo.value.candidates] == [
        "1",
        "2",
    ]


def test_fetch_symbol_requires_taxon_before_network() -> None:
    client = FakeGeneClient(records=[])

    with pytest.raises(CLIError, match="--taxon"):
        gene.fetch_gene(client, gene_id=None, symbol="BRCA1", taxon=None, links=[])

    assert client.calls == []


def test_cli_argument_validation() -> None:
    assert main(["gene", "fetch", "--symbol", "BRCA1", "--json"]) == 2
    assert (
        main(["gene", "fetch", "--gene-id", "672", "--symbol", "BRCA1", "--json"]) == 2
    )

    parser = build_parser()
    parsed = parser.parse_args(["gene", "links", "--gene-id", "672", "--to", "pubmed"])
    assert parsed.to == "pubmed"
    with pytest.raises(SystemExit):
        parser.parse_args(["gene", "links", "--gene-id", "672", "--to", "bad"])


def test_search_json_shape_uses_esearch_and_esummary() -> None:
    client = FakeGeneClient(records=[{"gene_id": "672", "official_symbol": "BRCA1"}])

    payload = gene.search_genes(client, "BRCA1", taxon="human", limit=5)

    assert payload["identifiers"] == {}
    assert payload["missing"] == []
    records = cast("list[dict[str, object]]", payload["records"])
    assert records[0]["gene_id"] == "672"
    assert client.calls[0][0] == "esearch"
    assert "txid9606" in str(client.calls[0][1]["term"])
    assert client.calls[1][0] == "esummary"


def test_fetch_returns_requested_links() -> None:
    client = FakeGeneClient(records=[{"gene_id": "672", "official_symbol": "BRCA1"}])

    payload = gene.fetch_gene(
        client,
        gene_id="672",
        symbol=None,
        taxon=None,
        links=["pubmed", "protein"],
    )

    record = cast("dict[str, object]", payload["record"])
    links = cast("dict[str, list[dict[str, object]]]", record["links"])
    assert links["pubmed"][0]["target_db"] == "pubmed"
    assert links["protein"][0]["target_db"] == "protein"


def test_429_handling_does_not_silently_fallback() -> None:
    limiter = RateLimiter(clock=lambda: 0.0, sleep=lambda _seconds: None)
    http = Always429HttpClient(limiter)
    client = NCBIClient(Config(email="user@example.org"), http)

    with pytest.raises(RateLimitError):
        client.request_json(
            "esearch", {"db": "gene", "term": "BRCA1", "retmode": "json"}
        )

    assert http.urls


def test_ncbi_client_adds_identity_parameters_and_ncbi_rate_limit_source() -> None:
    limiter = RecordingLimiter()
    http = RecordingHttpClient(limiter)
    client = NCBIClient(
        Config(email="agent@example.org", ncbi_api_key_command="printf secret"),
        http,
    )

    client.request_json("esearch", {"db": "gene", "term": "BRCA1", "retmode": "json"})

    query = parse_qs(urlparse(http.urls[0]).query)
    assert query["email"] == ["agent@example.org"]
    assert query["tool"] == ["biorefs-cli"]
    assert query["api_key"] == ["secret"]
    assert limiter.sources == ["ncbi-key"]


class FakeGeneClient:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records
        self.calls: list[tuple[str, dict[str, str | int]]] = []

    def request_json(self, endpoint: str, params: dict[str, str | int]) -> JsonObject:
        self.calls.append((endpoint, params))
        if endpoint == "esearch":
            ids = [str(record["gene_id"]) for record in self.records]
            return cast(
                "JsonObject", {"esearchresult": {"idlist": ids, "count": str(len(ids))}}
            )
        if endpoint == "esummary":
            ids = str(params["id"]).split(",")
            result: dict[str, object] = {"uids": ids}
            for record in self.records:
                gene_id = str(record["gene_id"])
                result[gene_id] = {
                    "name": record.get("official_symbol"),
                    "nomenclaturesymbol": record.get("official_symbol"),
                    "description": record.get("description", "description"),
                    "summary": "summary",
                    "organism": {"scientificname": "Homo sapiens", "taxid": 9606},
                }
            return cast("JsonObject", {"result": result})
        if endpoint == "elink":
            target_db = params["db"]
            return cast(
                "JsonObject",
                {
                    "linksets": [
                        {
                            "ids": [str(params["id"])],
                            "linksetdbs": [
                                {
                                    "dbto": target_db,
                                    "linkname": f"gene_{target_db}",
                                    "links": ["1"],
                                }
                            ],
                        }
                    ]
                },
            )
        raise AssertionError(endpoint)


class Always429HttpClient(HttpClient):
    def __init__(self, limiter: RateLimiter) -> None:
        super().__init__(
            timeout_seconds=3,
            retry_policy=RetryPolicy(attempts=1),
            rate_limiter=limiter,
        )
        self.urls: list[str] = []

    def _once(
        self, method: str, url: str, *, body: bytes | None, headers: dict[str, str]
    ) -> HttpResponse:
        assert headers is not None
        self.urls.append(url)
        return HttpResponse(status=429, headers={"retry-after": "0"}, body=b"slow down")


class RecordingLimiter(RateLimiter):
    def __init__(self) -> None:
        self.sources: list[str | object | None] = []

    def acquire(self, source: str | object | None) -> None:
        self.sources.append(source)


class RecordingHttpClient(HttpClient):
    def __init__(self, limiter: RecordingLimiter) -> None:
        super().__init__(timeout_seconds=3, rate_limiter=limiter)
        self.urls: list[str] = []

    def _once(
        self, method: str, url: str, *, body: bytes | None, headers: dict[str, str]
    ) -> HttpResponse:
        assert headers is not None
        self.urls.append(url)
        return HttpResponse(
            status=200, headers={}, body=json.dumps({"ok": True}).encode()
        )
