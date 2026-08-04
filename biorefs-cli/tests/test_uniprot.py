# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest
from biorefs_cli.commands.uniprot import (
    UniProtService,
    build_search_query,
    normalize_accession,
    parse_entry,
)
from biorefs_cli.errors import CLIError, RateLimitError
from biorefs_cli.main import main

if TYPE_CHECKING:
    from biorefs_cli.http import JsonObject


class FakeBackend:
    def __init__(
        self,
        *,
        search_payload: dict[str, object] | None = None,
        entry_payload: dict[str, object] | None = None,
        fasta_text: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.search_payload = search_payload or {}
        self.entry_payload = entry_payload or {}
        self.fasta_text = fasta_text or ""
        self.error = error
        self.search_params: dict[str, str] | None = None
        self.entry_accession: str | None = None
        self.entry_fields: str | None = None
        self.fasta_accession: str | None = None

    def search(self, params: dict[str, str]) -> JsonObject:
        self.search_params = params
        if self.error is not None:
            raise self.error
        return cast("JsonObject", self.search_payload)

    def entry(self, accession: str, fields: str) -> JsonObject:
        self.entry_accession = accession
        self.entry_fields = fields
        if self.error is not None:
            raise self.error
        return cast("JsonObject", self.entry_payload)

    def fasta(self, accession: str) -> str:
        self.fasta_accession = accession
        if self.error is not None:
            raise self.error
        return self.fasta_text


def brca1_entry() -> dict[str, object]:
    return {
        "entryType": "UniProtKB reviewed (Swiss-Prot)",
        "primaryAccession": "P38398",
        "uniProtkbId": "BRCA1_HUMAN",
        "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
        "proteinDescription": {
            "recommendedName": {
                "fullName": {"value": "Breast cancer type 1 susceptibility protein"}
            },
            "alternativeNames": [{"fullName": {"value": "RING finger protein 53"}}],
        },
        "genes": [{"geneName": {"value": "BRCA1"}, "synonyms": [{"value": "RNF53"}]}],
        "sequence": {"length": 1863},
        "comments": [
            {
                "commentType": "FUNCTION",
                "texts": [
                    {"value": "E3 ubiquitin-protein ligase that specifically..."}
                ],
            }
        ],
        "uniProtKBCrossReferences": [
            {
                "database": "PDB",
                "id": "1JM7",
                "properties": [
                    {"key": "Method", "value": "NMR"},
                    {"key": "Resolution", "value": "-"},
                    {"key": "Chains", "value": "A=1-110"},
                ],
            },
            {
                "database": "PDB",
                "id": "1T15",
                "properties": [
                    {"key": "Method", "value": "X-ray"},
                    {"key": "Resolution", "value": "2.50 A"},
                    {"key": "Chains", "value": "A=1646-1859"},
                ],
            },
            {"database": "GeneID", "id": "672", "properties": []},
            {
                "database": "RefSeq",
                "id": "NP_009225.1",
                "properties": [{"key": "NucleotideSequenceId", "value": "NM_007294.4"}],
            },
        ],
        "references": [
            {
                "citation": {
                    "citationType": "journal article",
                    "citationCrossReferences": [
                        {"database": "PubMed", "id": "7545954"},
                        {"database": "DOI", "id": "10.1126/science.7545954"},
                    ],
                }
            },
            {
                "citation": {
                    "citationType": "journal article",
                    "citationCrossReferences": [
                        {"database": "PubMed", "id": "7545954"},
                        {"database": "PubMed", "id": "8896459"},
                    ],
                }
            },
        ],
    }


def test_build_query_with_taxon_and_reviewed_filter() -> None:
    assert build_search_query("BRCA1", taxon="9606", reviewed=False) == (
        "BRCA1 AND organism_id:9606"
    )
    assert build_search_query("BRCA1", taxon="9606", reviewed=True) == (
        "BRCA1 AND organism_id:9606 AND reviewed:true"
    )
    assert build_search_query("p53", taxon=None, reviewed=False) == "p53"


def test_build_query_rejects_non_numeric_taxon() -> None:
    with pytest.raises(CLIError):
        build_search_query("BRCA1", taxon="human", reviewed=False)


def test_search_builds_params_and_parses_results() -> None:
    backend = FakeBackend(search_payload={"results": [brca1_entry()]})

    result = UniProtService(backend).search(
        "BRCA1", taxon="9606", reviewed=True, limit=10
    )

    assert backend.search_params is not None
    assert (
        backend.search_params["query"] == "BRCA1 AND organism_id:9606 AND reviewed:true"
    )
    assert backend.search_params["size"] == "10"
    assert backend.search_params["format"] == "json"
    records = result["records"]
    assert isinstance(records, list)
    assert records[0]["accession"] == "P38398"
    assert records[0]["entry_name"] == "BRCA1_HUMAN"
    assert records[0]["reviewed"] is True


def test_entry_parse_core_fields() -> None:
    record = parse_entry(brca1_entry())
    payload = record.to_json_dict()

    assert payload["accession"] == "P38398"
    assert payload["entry_name"] == "BRCA1_HUMAN"
    assert payload["reviewed"] is True
    assert payload["protein_name"] == "Breast cancer type 1 susceptibility protein"
    assert payload["genes"] == ["BRCA1"]
    assert payload["organism"] == "Homo sapiens"
    assert payload["tax_id"] == 9606
    assert payload["length"] == 1863


def test_entry_parse_extracts_pdb_xrefs() -> None:
    payload = parse_entry(brca1_entry()).to_json_dict()

    pdb = payload["pdb"]
    assert isinstance(pdb, list)
    assert pdb[0]["id"] == "1JM7"
    assert pdb[0]["method"] == "NMR"
    assert pdb[1]["id"] == "1T15"
    assert pdb[1]["resolution"] == "2.50 A"


def test_entry_parse_extracts_literature_pmids_deduped() -> None:
    payload = parse_entry(brca1_entry()).to_json_dict()

    assert payload["literature_pmids"] == ["7545954", "8896459"]


def test_entry_parse_extracts_entity_xrefs() -> None:
    payload = parse_entry(brca1_entry()).to_json_dict()

    xrefs = payload["xrefs"]
    assert isinstance(xrefs, dict)
    assert xrefs["GeneID"] == ["672"]
    assert xrefs["RefSeq"] == ["NP_009225.1"]


def test_entry_parse_extracts_function_text() -> None:
    payload = parse_entry(brca1_entry()).to_json_dict()

    function = payload["function"]
    assert isinstance(function, list)
    assert function[0].startswith("E3 ubiquitin-protein ligase")


def test_entry_parse_handles_unreviewed_and_submission_name() -> None:
    entry: dict[str, object] = {
        "entryType": "UniProtKB unreviewed (TrEMBL)",
        "primaryAccession": "E7ENB7",
        "uniProtkbId": "E7ENB7_HUMAN",
        "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
        "proteinDescription": {
            "submissionNames": [{"fullName": {"value": "BRCA1 protein"}}]
        },
        "sequence": {"length": 699},
    }
    payload = parse_entry(entry).to_json_dict()

    assert payload["reviewed"] is False
    assert payload["protein_name"] == "BRCA1 protein"
    assert "pdb" not in payload
    assert "literature_pmids" not in payload


def test_fetch_summary_requests_include_fields() -> None:
    backend = FakeBackend(entry_payload=brca1_entry())

    UniProtService(backend).fetch_summary("p38398", include=("function", "literature"))

    assert backend.entry_accession == "P38398"
    assert backend.entry_fields is not None
    assert "cc_function" in backend.entry_fields
    assert "lit_pubmed_id" in backend.entry_fields
    assert "xref_pdb" not in backend.entry_fields


def test_fasta_passthrough_behavior() -> None:
    fasta = ">sp|P38398|BRCA1_HUMAN Breast cancer type 1\nMDLSALRVEEVQNVINAMQK\n"
    backend = FakeBackend(fasta_text=fasta)

    result = UniProtService(backend).fetch_fasta("P38398")

    assert backend.fasta_accession == "P38398"
    assert result["content"] == fasta
    assert result["accession"] == "P38398"


def test_accession_normalization() -> None:
    cases = [
        (" p38398 ", "P38398"),
        ("Q9Y6K9", "Q9Y6K9"),
        ("P38398-2", "P38398-2"),
        ("A0A0B4J2F0", "A0A0B4J2F0"),
    ]
    for raw, normalized in cases:
        assert normalize_accession(raw) == normalized


def test_invalid_accessions_are_rejected() -> None:
    for raw in ["", "BRCA1", "../P38398", "P38398.fasta", "1JM7", "P38398/x"]:
        with pytest.raises(CLIError):
            normalize_accession(raw)


def test_cli_missing_accession(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["uniprot", "fetch"])

    captured = capsys.readouterr()
    assert status == 2
    assert "uniprot fetch requires --accession" in captured.err


def test_cli_invalid_format(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["uniprot", "fetch", "--accession", "P38398", "--format", "pdf"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "invalid choice" in captured.err


def test_429_handling_surfaces_rate_limited_error() -> None:
    backend = FakeBackend(error=RateLimitError())

    with pytest.raises(RateLimitError):
        UniProtService(backend).fetch_summary("P38398", include=("function",))


def test_json_roundtrip_of_summary_payload() -> None:
    backend = FakeBackend(entry_payload=brca1_entry())

    payload = UniProtService(backend).fetch_summary(
        "P38398", include=("function", "xrefs", "literature")
    )
    decoded = json.loads(json.dumps(payload))

    assert decoded["accession"] == "P38398"
    assert decoded["literature_pmids"] == ["7545954", "8896459"]
    assert decoded["pdb"][0]["id"] == "1JM7"
