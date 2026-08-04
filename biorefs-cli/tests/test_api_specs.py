# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Validate vendored API specs used by biorefs-cli reference docs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast


class ExpectedSpec(TypedDict):
    path: str
    endpoints: tuple[tuple[str, str], ...]


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "references" / "api-specs" / "raw"

EXPECTED: dict[str, ExpectedSpec] = {
    "openalex": {
        "path": "openalex-openapi.json",
        "endpoints": (("/works", "get"), ("/works/{id}", "get")),
    },
    "semantic-scholar-graph": {
        "path": "semantic-scholar-graph-v1-swagger.json",
        "endpoints": (
            ("/paper/{paper_id}", "get"),
            ("/paper/batch", "post"),
            ("/paper/search", "get"),
            ("/paper/search/bulk", "get"),
            ("/paper/search/match", "get"),
            ("/paper/{paper_id}/citations", "get"),
            ("/paper/{paper_id}/references", "get"),
        ),
    },
    "semantic-scholar-recommendations": {
        "path": "semantic-scholar-recommendations-v1-swagger.json",
        "endpoints": (("/papers/", "post"), ("/papers/forpaper/{paper_id}", "get")),
    },
    "europepmc": {
        "path": "europepmc-swagger.json",
        "endpoints": (
            ("/search", "get"),
            ("/searchPOST", "post"),
            ("/article/{source}/{id}", "get"),
            ("/{id}/fullTextXML", "get"),
        ),
    },
    "crossref": {
        "path": "crossref-swagger-docs.json",
        "endpoints": (("/works", "get"), ("/works/{doi}", "get")),
    },
}


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return cast("dict[str, object]", json.load(handle))


def test_documented_swagger_endpoints_exist() -> None:
    for name, spec_def in EXPECTED.items():
        spec = load_json(RAW / spec_def["path"])
        paths = spec.get("paths")
        assert isinstance(paths, dict), f"{name}: missing paths object"
        for endpoint, method in spec_def["endpoints"]:
            methods = paths.get(endpoint)
            assert isinstance(methods, dict), f"{name}: missing endpoint {endpoint}"
            assert method in methods, f"{name}: missing {method.upper()} {endpoint}"


def test_ncbi_datasets_yaml_snapshot_is_normalized() -> None:
    text = (RAW / "ncbi-datasets-openapi3.docs.yaml").read_text(encoding="utf-8")
    assert text.startswith("openapi: 3.0.1"), (
        "ncbi-datasets: missing OpenAPI version header"
    )
    assert "title: NCBI Datasets API" in text, "ncbi-datasets: missing API title"
    assert not any(line.endswith((" ", "\t")) for line in text.splitlines()), (
        "ncbi-datasets: trailing whitespace found"
    )
