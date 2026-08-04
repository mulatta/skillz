# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, cast

import pytest
from biorefs_cli.commands.structure import (
    SearchQuery,
    SearchService,
    build_query_from_args,
    build_search_payload,
    clean_sequence,
    normalize_pdb_id,
    normalize_uniprot_accession,
    parse_hits,
)
from biorefs_cli.errors import CLIError, HTTPError
from biorefs_cli.main import main
from biorefs_cli.rcsb_graphql import EntryMeta

if TYPE_CHECKING:
    from biorefs_cli.http import JsonObject


class FakeBackend:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload or {"total_count": 0, "result_set": []}

    def search(self, payload: dict[str, object]) -> JsonObject:
        return cast("JsonObject", self.payload)


class FakeEnricher:
    def __init__(
        self, meta: dict[str, EntryMeta] | None = None, error: Exception | None = None
    ) -> None:
        self.meta = meta or {}
        self.error = error
        self.requested: list[str] | None = None

    def entry_metadata(self, ids: list[str]) -> dict[str, EntryMeta]:
        self.requested = ids
        if self.error is not None:
            raise self.error
        return self.meta


def meta(pdb_id: str) -> EntryMeta:
    return EntryMeta(
        pdb_id, f"Structure {pdb_id}", "X-RAY DIFFRACTION", 1.85, ["Homo sapiens"]
    )


def args(**kwargs: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "query": None,
        "sequence": None,
        "sequence_file": None,
        "uniprot": None,
        "method": None,
        "max_resolution": None,
        "organism": None,
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


def query() -> SearchQuery:
    return SearchQuery("full_text", "BRCA1", None, None, None)


def test_pdb_and_uniprot_id_normalization() -> None:
    assert normalize_pdb_id(" 1jm7 ") == "1JM7"
    assert normalize_pdb_id("PDB_00001JM7") == "pdb_00001jm7"
    assert normalize_uniprot_accession(" p38398 ") == "P38398"
    for bad in ["JM7", "../1jm7", "12345"]:
        with pytest.raises(CLIError):
            normalize_pdb_id(bad)


def test_full_text_payload_uses_minimal_verbosity() -> None:
    payload = build_search_payload(
        build_query_from_args(args(query="BRCA1 BRCT")), limit=5, offset=0
    )
    assert payload["query"] == {
        "type": "terminal",
        "service": "full_text",
        "parameters": {"value": "BRCA1 BRCT"},
    }
    options = cast("dict[str, object]", payload["request_options"])
    assert options["paginate"] == {"start": 0, "rows": 5}
    assert options["results_verbosity"] == "minimal"


def test_offset_and_uniprot_node() -> None:
    payload = build_search_payload(
        build_query_from_args(args(uniprot="p38398")), limit=10, offset=20
    )
    options = cast("dict[str, object]", payload["request_options"])
    paginate = cast("dict[str, object]", options["paginate"])
    assert paginate["start"] == 20
    node = cast("dict[str, object]", payload["query"])
    params = cast("dict[str, object]", node["parameters"])
    assert params["value"] == "P38398"


def test_filters_compose_into_group() -> None:
    built = build_query_from_args(
        args(query="kinase", method="xray", max_resolution=2.5, organism="9606")
    )
    node = cast(
        "dict[str, object]", build_search_payload(built, limit=3, offset=0)["query"]
    )
    assert node["type"] == "group"
    assert len(cast("list[object]", node["nodes"])) == 4


def test_requires_exactly_one_primary() -> None:
    with pytest.raises(CLIError):
        build_query_from_args(args())
    with pytest.raises(CLIError):
        build_query_from_args(args(query="x", uniprot="P38398"))


def test_clean_sequence_strips_header() -> None:
    assert clean_sequence(">h\nMDLS\nALRV\n") == "MDLSALRV"
    with pytest.raises(CLIError):
        clean_sequence("MD12")


def test_parse_hits_reads_score() -> None:
    hits = parse_hits(
        {"result_set": [{"identifier": "3COJ", "score": 1.0}, {"identifier": "1T2V"}]}
    )
    assert hits[0].pdb_id == "3COJ"
    assert hits[0].score == 1.0
    assert hits[1].score is None


def test_run_enriches_hits() -> None:
    backend = FakeBackend(
        {"total_count": 145, "result_set": [{"identifier": "3COJ", "score": 1.0}]}
    )
    enricher = FakeEnricher({"3COJ": meta("3COJ")})
    result = SearchService(backend, enricher).run(query(), limit=1, offset=0)
    records = cast("list[dict[str, object]]", result["records"])
    assert result["total_count"] == 145
    assert records[0]["method"] == "X-RAY DIFFRACTION"
    assert records[0]["resolution"] == 1.85


def test_run_empty_results_no_enrich_no_warning() -> None:
    backend = FakeBackend({"total_count": 0, "result_set": []})
    enricher = FakeEnricher()
    result = SearchService(backend, enricher).run(query(), limit=5, offset=0)
    assert result["records"] == []
    assert result["total_count"] == 0
    assert "warnings" not in result
    assert enricher.requested is None


def test_run_degrades_when_enrichment_fails() -> None:
    backend = FakeBackend(
        {"total_count": 1, "result_set": [{"identifier": "3COJ", "score": 1.0}]}
    )
    enricher = FakeEnricher(error=HTTPError("boom"))
    result = SearchService(backend, enricher).run(query(), limit=1, offset=0)
    records = cast("list[dict[str, object]]", result["records"])
    assert "method" not in records[0]
    assert result["warnings"] == ["metadata enrichment unavailable"]


def test_cli_rejects_no_query(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["structure", "search"])
    captured = capsys.readouterr()
    assert status == 2
    assert "exactly one" in captured.err


def test_cli_offset_validation(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["structure", "search", "kinase", "--offset", "-1"])
    captured = capsys.readouterr()
    assert status == 2
    assert "--offset" in captured.err
