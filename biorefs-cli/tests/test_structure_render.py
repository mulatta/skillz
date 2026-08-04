# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest
from biorefs_cli.commands.structure import (
    parse_include,
    print_info_table,
    print_search_table,
    validate_organism,
)
from biorefs_cli.errors import CLIError


def search_result() -> dict[str, object]:
    return {
        "source": "rcsb",
        "total_count": 145,
        "offset": 0,
        "records": [
            {
                "pdb_id": "3COJ",
                "score": 1.0,
                "method": "X-RAY DIFFRACTION",
                "resolution": 1.85,
                "organisms": ["Homo sapiens"],
                "title": "BRCA1 BRCT repeats",
            }
        ],
    }


def info_result() -> dict[str, object]:
    return {
        "source": "rcsb",
        "pdb_id": "1T15",
        "title": "BRCA1 BRCT repeats",
        "method": "X-RAY DIFFRACTION",
        "resolution": 1.85,
        "deposit_date": "2004-04-15",
        "chain_count": 2,
        "ligands": ["ZN"],
        "entities": [
            {
                "entity_id": "1",
                "description": "BRCA1",
                "organism": "Homo sapiens",
                "uniprot": ["P38398"],
            }
        ],
    }


def test_print_search_table_columns_and_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_search_table(search_result())
    out = capsys.readouterr().out
    header = out.splitlines()[0]
    for column in ("Rank", "PDB ID", "Method", "Resolution", "Organism", "Title"):
        assert column in header
    assert "3COJ" in out
    assert "X-RAY DIFFRACTION" in out
    assert "1.85" in out
    assert "Homo sapiens" in out
    assert "BRCA1 BRCT repeats" in out
    assert "Showing 1 of 145 matches." in out


def test_print_search_table_empty(capsys: pytest.CaptureFixture[str]) -> None:
    print_search_table({"total_count": 0, "records": []})
    out = capsys.readouterr().out
    assert "No structures found" in out
    assert "0" in out


def test_print_info_table_fields_and_entities(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_info_table(info_result())
    out = capsys.readouterr().out
    for field in ("PDB ID", "Title", "Method", "Resolution", "Deposited", "Chains"):
        assert field in out
    assert "1T15" in out
    assert "2004-04-15" in out
    assert "ZN" in out
    # entity sub-table
    for column in ("Entity", "Description", "Organism", "UniProt"):
        assert column in out
    assert "P38398" in out


def test_print_info_table_without_entities(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = info_result()
    del result["entities"]
    print_info_table(result)
    out = capsys.readouterr().out
    assert "Entity" not in out
    assert "1T15" in out


def test_parse_include_valid() -> None:
    assert parse_include(None) == ()
    assert parse_include("entities") == ("entities",)
    assert parse_include(" entities , ") == ("entities",)


def test_parse_include_invalid() -> None:
    with pytest.raises(CLIError):
        parse_include("ligands")


def test_validate_organism() -> None:
    assert validate_organism(None) is None
    assert validate_organism(" 9606 ") == "9606"
    with pytest.raises(CLIError):
        validate_organism("human")
