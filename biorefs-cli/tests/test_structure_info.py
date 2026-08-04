# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from biorefs_cli.commands.structure import (
    InfoService,
    build_info_result,
    parse_entry,
)
from biorefs_cli.main import main

if TYPE_CHECKING:
    from biorefs_cli.http import JsonObject


class FakeBackend:
    def __init__(
        self,
        entry: dict[str, object],
        entities: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.entry_payload = entry
        self.entities = entities or {}
        self.entity_calls: list[tuple[str, str]] = []

    def entry(self, pdb_id: str) -> JsonObject:
        return cast("JsonObject", self.entry_payload)

    def polymer_entity(self, pdb_id: str, entity_id: str) -> JsonObject:
        self.entity_calls.append((pdb_id, entity_id))
        return cast("JsonObject", self.entities[entity_id])


def xray_entry() -> dict[str, object]:
    return {
        "struct": {"title": "BRCA1 BRCT repeats"},
        "exptl": [{"method": "X-RAY DIFFRACTION"}],
        "rcsb_entry_info": {
            "resolution_combined": [1.85],
            "nonpolymer_bound_components": ["ZN"],
            "deposited_polymer_entity_instance_count": 2,
        },
        "rcsb_accession_info": {"deposit_date": "2004-04-15T00:00:00.000+00:00"},
        "rcsb_entry_container_identifiers": {"polymer_entity_ids": ["1"]},
    }


def brca1_entity() -> dict[str, object]:
    return {
        "rcsb_polymer_entity": {"pdbx_description": "BRCA1"},
        "rcsb_entity_source_organism": [
            {"scientific_name": "Homo sapiens", "ncbi_taxonomy_id": 9606},
        ],
        "rcsb_polymer_entity_align": [
            {
                "reference_database_name": "UniProt",
                "reference_database_accession": "P38398",
            },
        ],
    }


def test_parse_entry_core_fields() -> None:
    payload = parse_entry("1T15", xray_entry()).to_json_dict()
    assert payload["pdb_id"] == "1T15"
    assert payload["method"] == "X-RAY DIFFRACTION"
    assert payload["resolution"] == 1.85
    assert payload["deposit_date"] == "2004-04-15"
    assert payload["ligands"] == ["ZN"]
    assert payload["chain_count"] == 2


def test_include_entities_fetches_uniprot() -> None:
    backend = FakeBackend(xray_entry(), {"1": brca1_entity()})
    result = InfoService(backend).fetch("1t15", include=("entities",))
    assert backend.entity_calls == [("1T15", "1")]
    entities = cast("list[dict[str, object]]", result["entities"])
    assert entities[0]["uniprot"] == ["P38398"]


def test_default_excludes_entities() -> None:
    backend = FakeBackend(xray_entry())
    result = InfoService(backend).fetch("1T15", include=())
    assert "entities" not in result
    assert backend.entity_calls == []


def test_build_info_result_single_vs_batch() -> None:
    assert build_info_result([{"pdb_id": "1JM7"}]) == {"pdb_id": "1JM7"}
    many = build_info_result([{"pdb_id": "1JM7"}, {"pdb_id": "1T15"}])
    assert isinstance(many, dict)
    assert len(cast("list[object]", many["records"])) == 2


def test_cli_invalid_pdb_id(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["structure", "info", "../etc"])
    assert status == 2
    assert "invalid PDB id" in capsys.readouterr().err
