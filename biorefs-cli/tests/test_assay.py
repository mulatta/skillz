# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from biorefs_cli.commands.assay import (
    PubChemAssayClient,
    handle_http_error,
    parse_assay_description,
    parse_concise_activity,
    parse_include,
)
from biorefs_cli.errors import RateLimitError
from biorefs_cli.http import HttpClient, JsonObject, JsonValue
from biorefs_cli.main import main

if TYPE_CHECKING:
    from collections.abc import Sequence


class FakeHttp(HttpClient):
    def __init__(self, responses: dict[str, JsonObject]) -> None:
        self.responses = responses
        self.urls: list[str] = []
        self.rate_limit_sources: list[str | None] = []

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> JsonObject:
        _ = headers
        self.urls.append(url)
        self.rate_limit_sources.append(rate_limit_source)
        for suffix, payload in self.responses.items():
            if url.endswith(suffix):
                return payload
        msg = f"missing fake response for {url}"
        raise AssertionError(msg)


COMPOUND_CIDS: JsonObject = {"IdentifierList": {"CID": [23725625]}}
ASSAY_SUMMARY: JsonObject = {
    "AssaySummaries": {
        "AssaySummary": [
            {
                "AID": 504526,
                "Name": "PARP1 inhibition assay",
                "AssayType": "confirmatory",
                "ActivityOutcome": "Active",
                "SourceName": "ChEMBL",
                "TargetGeneID": 142,
                "TargetGeneSymbol": "PARP1",
                "TargetName": "poly(ADP-ribose) polymerase 1",
                "ActiveCount": 7,
                "TestedSIDCount": 12,
            },
        ],
    },
}
ASSAY_DESCRIPTION: JsonObject = {
    "PC_AssayContainer": [
        {
            "assay": {
                "descr": {
                    "aid": {"id": 504526},
                    "name": "PARP1 inhibition assay",
                    "description": ["Measures inhibition of PARP1."],
                    "activity_outcome_method": "confirmatory",
                    "aid_source": {
                        "db": {"name": "ChEMBL", "source_id": {"str": "CHEMBL-A1"}},
                    },
                    "xref": [{"xref": {"pmid": 23103855}}],
                    "target": [
                        {
                            "name": "poly(ADP-ribose) polymerase 1",
                            "mol_id": 156523970,
                            "organism": {"org": {"taxname": "Homo sapiens"}},
                            "xref": [
                                {"xref": {"gene": 142}},
                                {"xref": {"protein_gi": 156523970}},
                            ],
                        },
                    ],
                },
            },
        },
    ],
}


def concise_fixture(row_count: int) -> JsonObject:
    rows: list[JsonValue] = [activity_row(index) for index in range(row_count)]
    return {
        "PC_AssaySubmit": {
            "assay": {
                "descr": {
                    "aid": {"id": 504526},
                    "results": [
                        {"tid": 1, "name": "PUBCHEM_ACTIVITY_OUTCOME"},
                        {"tid": 2, "name": "IC50", "unit": "nM", "type": "float"},
                    ],
                },
            },
            "data": rows,
        },
    }


def activity_row(index: int) -> JsonObject:
    return {
        "sid": 1000 + index,
        "cid": 23725625,
        "outcome": 2 if index % 2 == 0 else 1,
        "data": [
            {
                "tid": 1,
                "value": {"sval": "Active" if index % 2 == 0 else "Inactive"},
            },
            {"tid": 2, "value": {"fval": float(index) + 0.5}},
        ],
    }


def client_with(
    responses: dict[str, JsonObject],
) -> tuple[PubChemAssayClient, FakeHttp]:
    http = FakeHttp(responses)
    return PubChemAssayClient(http=http, email="user@example.org"), http


def test_compound_name_routes_to_cid_before_assay_summary() -> None:
    client, http = client_with(
        {
            "/compound/name/olaparib/cids/JSON": COMPOUND_CIDS,
            "/compound/cid/23725625/assaysummary/JSON": ASSAY_SUMMARY,
        },
    )

    result = client.search_assays(target=None, compound="olaparib", limit=5)

    assert http.urls[0].endswith("/compound/name/olaparib/cids/JSON")
    assert http.urls[1].endswith("/compound/cid/23725625/assaysummary/JSON")
    assert http.rate_limit_sources == ["pubchem", "pubchem"]
    identifiers = cast("JsonObject", result["identifiers"])
    compound = cast("JsonObject", identifiers["compound"])
    assert compound["cid"] == 23725625
    rows = cast("Sequence[JsonObject]", result["results"])
    assert rows[0]["aid"] == 504526


def test_assay_summary_parse_preserves_activity_and_target_hints() -> None:
    client, _http = client_with(
        {"/compound/cid/23725625/assaysummary/JSON": ASSAY_SUMMARY},
    )

    rows = client.compound_assay_summary(23725625, "2026-05-21T00:00:00Z")

    assert rows[0]["name"] == "PARP1 inhibition assay"
    assert rows[0]["activity_outcome"] == "Active"
    assert rows[0]["source"] == "ChEMBL"
    summary = cast("JsonObject", rows[0]["activity_summary"])
    assert summary["active_count"] == 7
    target_hints = cast("Sequence[JsonObject]", rows[0]["target_hints"])
    assert target_hints[0]["gene_id"] == 142


def test_target_parse_from_assay_description() -> None:
    parsed = parse_assay_description(ASSAY_DESCRIPTION, "2026-05-21T00:00:00Z")

    assert parsed["description"] == "Measures inhibition of PARP1."
    targets = cast("Sequence[JsonObject]", parsed["targets"])
    assert targets[0]["gene_id"] == "142"
    assert targets[0]["protein_gi"] == "156523970"
    assert targets[0]["organism"] == "Homo sapiens"
    refs = cast("Sequence[JsonObject]", parsed["pubmed_refs"])
    assert refs[0]["pmid"] == "23103855"


def test_activity_rows_parse_and_truncation_metadata() -> None:
    parsed = parse_concise_activity(concise_fixture(30), limit=25)

    rows = cast("Sequence[JsonObject]", parsed["rows"])
    summary = cast("JsonObject", parsed["summary"])
    outcomes = cast("JsonObject", summary["outcomes"])
    assert len(rows) == 25
    assert parsed["truncated"] is True
    assert summary["total_rows"] == 30
    assert outcomes["active"] == 15
    assert rows[0]["activity_name"] == "IC50"
    assert rows[0]["activity_unit"] == "nM"
    assert rows[0]["outcome"] == "active"
    assert "no mechanism inferred" in str(rows[0]["evidence_note"])


def test_fetch_includes_requested_sections() -> None:
    client, _http = client_with(
        {
            "/assay/aid/504526/description/JSON": ASSAY_DESCRIPTION,
            "/assay/aid/504526/concise/JSON": concise_fixture(2),
        },
    )

    result = client.fetch_assay(
        aid=504526,
        include=("description", "targets", "concise", "activity"),
    )

    assert result["aid"] == 504526
    assert result["description"] == "Measures inhibition of PARP1."
    targets = cast("Sequence[JsonObject]", result["targets"])
    assert targets[0]["gene_id"] == "142"
    activity = cast("Sequence[JsonObject]", result["activity"])
    assert len(activity) == 2
    truncated = cast("JsonObject", result["truncated"])
    assert truncated["activity"] is False


def test_cli_argument_validation_requires_search_query(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(["assay", "search"])

    assert status == 2
    captured = capsys.readouterr()
    assert "requires --target and/or --compound" in captured.err


def test_cli_argument_validation_rejects_unknown_include() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["assay", "fetch", "--aid", "1", "--include", "description,bogus"])

    assert exc_info.value.code == 2


def test_parse_include_accepts_final_sections() -> None:
    assert parse_include("description,targets,concise,activity") == (
        "description",
        "targets",
        "concise",
        "activity",
    )


def test_rate_limited_error_is_structured_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = handle_http_error(
        RateLimitError(retry_after_seconds=2.0),
        json_output=True,
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "rate limited" not in captured.err
    assert "pubchem-rate-limited" in captured.out
    assert "retry_after_seconds" in captured.out
