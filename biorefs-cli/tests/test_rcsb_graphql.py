from __future__ import annotations

from biorefs_cli.rcsb_graphql import build_query, parse_entries


def graphql_response() -> dict[str, object]:
    return {
        "data": {
            "entries": [
                {
                    "rcsb_id": "1T15",
                    "struct": {"title": "Crystal Structure of the Brca1 BRCT Domains"},
                    "exptl": [{"method": "X-RAY DIFFRACTION"}],
                    "rcsb_entry_info": {"resolution_combined": [1.85]},
                    "polymer_entities": [
                        {
                            "rcsb_entity_source_organism": [
                                {"scientific_name": "Homo sapiens"}
                            ]
                        },
                        {"rcsb_entity_source_organism": [{"scientific_name": None}]},
                    ],
                },
                {
                    "rcsb_id": "1JM7",
                    "struct": {"title": "Solution structure of the BRCA1/BARD1"},
                    "exptl": [{"method": "SOLUTION NMR"}],
                    "rcsb_entry_info": {"resolution_combined": None},
                    "polymer_entities": [
                        {
                            "rcsb_entity_source_organism": [
                                {"scientific_name": "Homo sapiens"}
                            ]
                        }
                    ],
                },
            ]
        }
    }


def test_build_query_embeds_ids() -> None:
    payload = build_query(["1T15", "1JM7"])
    assert '"1T15","1JM7"' in str(payload["query"])
    assert "entries(entry_ids:" in str(payload["query"])


def test_parse_entries_maps_metadata_by_id() -> None:
    meta = parse_entries(graphql_response())

    xray = meta["1T15"]
    assert xray.method == "X-RAY DIFFRACTION"
    assert xray.resolution == 1.85
    assert xray.organisms == ["Homo sapiens"]
    assert str(xray.title).startswith("Crystal Structure")

    nmr = meta["1JM7"]
    assert nmr.method == "SOLUTION NMR"
    assert nmr.resolution is None


def test_parse_entries_handles_empty() -> None:
    assert parse_entries({}) == {}
    assert parse_entries({"data": {"entries": []}}) == {}


def test_organisms_dedup_and_order_across_entities() -> None:
    payload: dict[str, object] = {
        "data": {
            "entries": [
                {
                    "rcsb_id": "9XYZ",
                    "struct": {"title": "complex"},
                    "exptl": [{"method": "X-RAY DIFFRACTION"}],
                    "rcsb_entry_info": {"resolution_combined": [2.0]},
                    "polymer_entities": [
                        {
                            "rcsb_entity_source_organism": [
                                {"scientific_name": "Homo sapiens"}
                            ]
                        },
                        {
                            "rcsb_entity_source_organism": [
                                {"scientific_name": "Homo sapiens"}
                            ]
                        },
                        {
                            "rcsb_entity_source_organism": [
                                {"scientific_name": "Mus musculus"}
                            ]
                        },
                    ],
                }
            ]
        }
    }
    assert parse_entries(payload)["9XYZ"].organisms == ["Homo sapiens", "Mus musculus"]
