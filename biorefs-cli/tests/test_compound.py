# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from biorefs_cli.commands import compound
from biorefs_cli.errors import CLIError
from biorefs_cli.main import build_parser

if TYPE_CHECKING:
    from biorefs_cli.http import JsonObject


class FixtureHttp:
    def __init__(self, responses: dict[str, JsonObject]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str | None]] = []

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> JsonObject:
        _ = headers
        self.calls.append((url, rate_limit_source))
        return self.responses[url]


def cids_url(kind: str, query: str) -> str:
    return f"{compound.PUG_REST_BASE}/compound/{kind}/{query}/cids/JSON"


def property_url(cids: str) -> str:
    properties = ",".join(compound.PROPERTY_NAMES)
    return f"{compound.PUG_REST_BASE}/compound/cid/{cids}/property/{properties}/JSON"


def cids_fixture(*cids: int) -> JsonObject:
    return {"IdentifierList": {"CID": list(cids)}}


def property_fixture(cid: int = 2244) -> JsonObject:
    return {
        "PropertyTable": {
            "Properties": [
                {
                    "CID": cid,
                    "Title": "Aspirin",
                    "MolecularFormula": "C9H8O4",
                    "MolecularWeight": 180.16,
                    "CanonicalSMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
                    "IsomericSMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
                    "InChI": "InChI=1S/C9H8O4",
                    "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
                    "IUPACName": "2-acetyloxybenzoic acid",
                    "XLogP": 1.2,
                    "TPSA": 63.6,
                    "Charge": 0,
                    "Complexity": 212,
                }
            ]
        }
    }


def test_search_routes_name_cid_smiles_inchikey_and_formula_inputs() -> None:
    cases: list[tuple[compound.QueryType, str, str]] = [
        ("name", "aspirin", cids_url("name", "aspirin")),
        ("smiles", "CC(=O)O", cids_url("smiles", "CC%28%3DO%29O")),
        (
            "inchikey",
            "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            cids_url("inchikey", "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"),
        ),
        ("formula", "C9H8O4", cids_url("fastformula", "C9H8O4")),
    ]
    for query_type, query, expected_url in cases:
        http = FixtureHttp(
            {expected_url: cids_fixture(2244), property_url("2244"): property_fixture()}
        )
        client = compound.CompoundClient(http)

        result = client.search(query, query_type, limit=5)

        assert result["identifiers"] == {"cids": [2244]}
        assert http.calls[0] == (expected_url, "pubchem")

    http = FixtureHttp({property_url("2244"): property_fixture()})
    result = compound.CompoundClient(http).search("2244", "cid", limit=5)

    assert result["identifiers"] == {"cids": [2244]}
    assert http.calls == [(property_url("2244"), "pubchem")]


def test_property_json_parse_normalizes_concise_compound_fields() -> None:
    records = compound.parse_properties(property_fixture(), property_url("2244"))

    assert records[0]["cid"] == 2244
    assert records[0]["name"] == "Aspirin"
    assert records[0]["molecular_formula"] == "C9H8O4"
    assert records[0]["molecular_weight"] == 180.16
    assert records[0]["canonical_smiles"] == "CC(=O)OC1=CC=CC=C1C(=O)O"
    assert records[0]["inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    assert records[0]["provenance"][0]["source"] == "PubChem PUG-REST"


def pug_view_fixture() -> JsonObject:
    return {
        "Record": {
            "Reference": [
                {
                    "ReferenceNumber": 1,
                    "SourceName": "DrugBank",
                    "URL": "https://example.test/drugbank",
                },
                {
                    "ReferenceNumber": 2,
                    "SourceName": "GHS",
                    "URL": "https://example.test/ghs",
                },
            ],
            "Section": [
                {
                    "TOCHeading": "Record Description",
                    "Information": [
                        {
                            "ReferenceNumber": 1,
                            "Value": {
                                "StringWithMarkup": [
                                    {"String": "Aspirin is an analgesic."}
                                ]
                            },
                        }
                    ],
                },
                {
                    "TOCHeading": "Safety and Hazards",
                    "Section": [
                        {
                            "TOCHeading": "GHS Classification",
                            "Information": [
                                {
                                    "ReferenceNumber": 2,
                                    "Name": "Signal",
                                    "Value": {
                                        "StringWithMarkup": [{"String": "Warning"}]
                                    },
                                }
                            ],
                        }
                    ],
                },
                {
                    "TOCHeading": "Classification",
                    "Information": [
                        {
                            "Name": "MeSH",
                            "Value": {
                                "StringWithMarkup": [
                                    {"String": "Anti-Inflammatory Agents"}
                                ]
                            },
                        }
                    ],
                },
            ],
        }
    }


def test_pug_view_section_extraction_for_description_safety_classification() -> None:
    sections = compound.extract_pug_view_sections(
        pug_view_fixture(),
        ["description", "safety", "classification"],
        f"{compound.PUG_VIEW_BASE}/data/compound/2244/JSON",
        "CID:2244",
    )

    assert sections["description"][0]["text"] == "Aspirin is an analgesic."
    assert sections["description"][0]["sources"][0]["source_name"] == "DrugBank"
    assert sections["safety"][0]["text"] == "Warning"
    assert sections["classification"][0]["text"] == "Anti-Inflammatory Agents"


def test_fetch_name_ambiguity_returns_candidate_list() -> None:
    name_url = cids_url("name", "ambiguous")
    http = FixtureHttp(
        {
            name_url: cids_fixture(1, 2),
            property_url("1,2"): {
                "PropertyTable": {
                    "Properties": [
                        {"CID": 1, "Title": "Candidate 1"},
                        {"CID": 2, "Title": "Candidate 2"},
                    ]
                }
            },
        }
    )

    result = compound.CompoundClient(http).fetch(
        cid=None, name="ambiguous", include=["properties"]
    )

    assert result["status"] == "ambiguous"
    assert result["identifiers"] == {"cids": [1, 2]}
    assert [item["cid"] for item in result["candidates"]] == [1, 2]


def test_xrefs_parse_requested_targets_with_provenance() -> None:
    pubmed_url = f"{compound.PUG_REST_BASE}/compound/cid/2244/xrefs/PubMedID/JSON"
    gene_url = f"{compound.PUG_REST_BASE}/compound/cid/2244/xrefs/GeneID/JSON"
    http = FixtureHttp(
        {
            pubmed_url: {
                "InformationList": {
                    "Information": [{"CID": 2244, "PubMedID": ["1", "2"]}]
                }
            },
            gene_url: {
                "InformationList": {"Information": [{"CID": 2244, "GeneID": ["10"]}]}
            },
        }
    )

    result = compound.CompoundClient(http).xrefs(2244, ["pubmed", "gene"])

    assert result["missing"] == []
    assert result["xrefs"][0]["target"] == {"type": "pubmed", "pmid": "1"}
    assert result["xrefs"][2]["target"] == {"type": "gene", "gene_id": "10"}
    assert result["xrefs"][0]["sources"][0]["source"] == "PubChem PUG-REST"


def test_bioactivity_row_parse_and_active_filter() -> None:
    url = f"{compound.PUG_REST_BASE}/compound/cid/2244/assaysummary/JSON"
    http = FixtureHttp(
        {
            url: {
                "Table": {
                    "Columns": {
                        "Column": [
                            "AID",
                            "Activity Outcome",
                            "Activity Name",
                            "Activity Value",
                            "Activity Unit",
                            "Target Name",
                            "GeneID",
                            "Source Name",
                        ]
                    },
                    "Row": [
                        {
                            "Cell": [
                                "100",
                                "Active",
                                "IC50",
                                5.0,
                                "nM",
                                "PTGS1",
                                "5742",
                                "PubChem",
                            ]
                        },
                        {
                            "Cell": [
                                "101",
                                "Inactive",
                                "IC50",
                                1000.0,
                                "nM",
                                "PTGS2",
                                "5743",
                                "PubChem",
                            ]
                        },
                    ],
                }
            }
        }
    )

    result = compound.CompoundClient(http).bioactivity(
        2244, target=None, active_only=True, limit=10
    )

    assert result["counts"] == {"before_filter": 2, "returned": 1}
    assert result["rows"][0]["outcome"] == "active"
    assert result["rows"][0]["target"] == {
        "name": "PTGS1",
        "gene_id": "5742",
        "protein_accession": "",
    }


def test_cli_argument_validation() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["compound", "fetch", "--cid", "2244", "--name", "aspirin"])
    with pytest.raises(SystemExit):
        parser.parse_args(["compound", "bioactivity", "--cid", "0"])
    with pytest.raises(CLIError):
        compound.run_command(
            parser.parse_args(
                ["compound", "fetch", "--cid", "2244", "--include", "bad"]
            ),
            compound.CompoundClient(FixtureHttp({})),
        )
    with pytest.raises(CLIError):
        compound.run_command(
            parser.parse_args(["compound", "search", "not-a-cid", "--type", "cid"]),
            compound.CompoundClient(FixtureHttp({})),
        )
