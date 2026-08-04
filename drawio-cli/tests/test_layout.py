# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from pathlib import Path

import pytest

from drawio_cli.document import DrawioDocument
from drawio_cli.layout import layout_graph
from drawio_cli.validate import validate_document


@pytest.mark.parametrize(
    ("nodes", "message"),
    [
        ([{"id": "api service"}, {"id": "api-service"}], "cell id collision"),
        ([{"id": "api", "width": 0}], "positive finite dimensions"),
        ([{"id": "api", "height": "nan"}], "positive finite dimensions"),
    ],
)
def test_layout_rejects_invalid_nodes(
    tmp_path: Path, nodes: list[dict[str, object]], message: str
) -> None:
    graph_path = tmp_path / "invalid.json"
    graph_path.write_text(json.dumps({"nodes": nodes}))

    with pytest.raises(ValueError, match=message):
        layout_graph(graph_path, tmp_path / "out.drawio", dot="dot")


def test_layout_rejects_non_object_graph(tmp_path: Path) -> None:
    graph_path = tmp_path / "invalid.json"
    graph_path.write_text("[]")

    with pytest.raises(ValueError, match="graph JSON must be an object"):
        layout_graph(graph_path, tmp_path / "out.drawio", dot="dot")


def test_layout_refuses_existing_output(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.json"
    output = tmp_path / "existing.drawio"
    graph_path.write_text(json.dumps({"nodes": [{"id": "api"}]}))
    output.write_text("keep")

    with pytest.raises(ValueError, match="already exists"):
        layout_graph(graph_path, output, dot="dot")
    assert output.read_text() == "keep"


def test_layout_writes_valid_nested_groups(tmp_path: Path) -> None:
    graph = {
        "direction": "LR",
        "nodes": [
            {"id": "client", "label": "Client", "group": "edge"},
            {"id": "api service", "label": "API", "group": "core"},
            {"id": "db", "label": "DB", "group": "core/data"},
        ],
        "edges": [{"source": "client", "target": "api service", "label": "HTTPS"}],
    }
    graph_path = tmp_path / "graph.json"
    out = tmp_path / "out.drawio"
    graph_path.write_text(json.dumps(graph))

    layout_graph(graph_path, out, dot="dot")

    doc = DrawioDocument.from_file(out)
    result = validate_document(doc)
    model = doc.page_model(page_index=0)
    parent_group = model.find("root/mxCell[@id='cell-group-core']")
    nested_group = model.find("root/mxCell[@id='cell-group-core-data']")
    edge = model.find("root/mxCell[@id='cell-edge-0-client-api-service']")
    assert result.errors == []
    assert parent_group is not None
    assert nested_group is not None and nested_group.get("parent") == "cell-group-core"
    parent_geometry = parent_group.find("mxGeometry")
    nested_geometry = nested_group.find("mxGeometry")
    assert parent_geometry is not None and nested_geometry is not None
    assert float(nested_geometry.get("x", "0")) > 0
    assert float(nested_geometry.get("width", "0")) < float(
        parent_geometry.get("width", "0")
    )
    assert edge is not None and edge.get("value") == "HTTPS"
