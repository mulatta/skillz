from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from drawio_cli.shapes import ShapeIndex, load_index, search_shapes, soundex


def test_soundex_codes_s_as_two() -> None:
    assert soundex("system") == "S235"


@pytest.fixture
def shape_index(tmp_path: Path) -> ShapeIndex:
    data = {
        "schemaVersion": 1,
        "entries": [
            {
                "id": "aws-lambda",
                "kind": "vertex",
                "title": "Lambda",
                "tags": ["aws", "lambda", "function"],
                "libraries": ["aws4"],
                "style": "shape=mxgraph.aws4.lambda;",
                "width": 78,
                "height": 78,
            },
            {
                "id": "azure-function",
                "kind": "vertex",
                "title": "Function App",
                "tags": ["azure", "function", "app"],
                "libraries": ["azure2"],
                "style": "shape=mxgraph.azure2.function_app;",
                "width": 78,
                "height": 78,
            },
            {
                "id": "router",
                "kind": "vertex",
                "title": "Router",
                "tags": ["cisco", "router", "network"],
                "libraries": ["cisco"],
                "style": "shape=mxgraph.cisco.router;",
                "width": 80,
                "height": 60,
            },
        ],
    }
    path = tmp_path / "shape-index.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(data, handle)
    return load_index(path)


def test_load_index_rejects_non_object_entries(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"entries": [42]}))

    with pytest.raises(ValueError, match="entry 0 must be an object"):
        load_index(path)


def test_search_strong_and_filter(shape_index: ShapeIndex) -> None:
    result = search_shapes(shape_index, "aws lambda", limit=5)
    camel_case = search_shapes(shape_index, "awsLambda", limit=5)
    filtered = search_shapes(shape_index, "function", limit=5, library="azure2")

    assert result.strong is True
    assert [entry.title for entry in result.entries] == ["Lambda"]
    assert [entry.title for entry in camel_case.entries] == ["Lambda"]
    assert [entry.title for entry in filtered.entries] == ["Function App"]
    with pytest.raises(ValueError, match="limit must be positive"):
        search_shapes(shape_index, "lambda", limit=0)


@pytest.mark.parametrize(
    ("fuzzy", "expected"),
    [(False, []), (True, ["Router", "Lambda"])],
)
def test_or_fallback_requires_fuzzy(
    shape_index: ShapeIndex, fuzzy: bool, expected: list[str]
) -> None:
    result = search_shapes(shape_index, "aws router", limit=5, fuzzy=fuzzy)

    assert [entry.title for entry in result.entries] == expected
