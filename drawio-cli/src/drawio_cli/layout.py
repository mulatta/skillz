from __future__ import annotations

import html
import json
import math
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .atomic import atomic_write_bytes
from .document import DrawioDocument
from .validate import validate_document

DEFAULT_NODE_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"
)
GROUP_STYLE = "rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#999999;dashed=1;verticalAlign=top;"
EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
)
PX_PER_INCH = 100.0
GRID = 10


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    style: str
    width: float
    height: float
    group: str | None


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    label: str


@dataclass(frozen=True)
class PlainNode:
    x: float
    y: float


@dataclass(frozen=True)
class PlainEdge:
    points: list[tuple[float, float]]


@dataclass(frozen=True)
class PlainLayout:
    nodes: dict[str, PlainNode]
    edges: dict[tuple[str, str], list[PlainEdge]]


def _snap(value: float) -> int:
    return int(round(value / GRID) * GRID)


def _dot_quote(value: str) -> str:
    return json.dumps(value)


def _cell_id(value: str) -> str:
    return "cell-" + "".join(
        char if char.isalnum() or char in {"_", "-"} else "-" for char in value
    )


def _load_graph(
    path: Path, direction: str | None
) -> tuple[str, list[Node], list[Edge]]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("graph JSON must be an object")
    graph_direction = direction or str(data.get("direction", "TB"))
    if graph_direction not in {"TB", "LR"}:
        raise ValueError("direction must be TB or LR")

    nodes_raw = data.get("nodes")
    edges_raw = data.get("edges", [])
    if not isinstance(nodes_raw, list) or not isinstance(edges_raw, list):
        raise ValueError("nodes and edges must be lists")

    nodes: list[Node] = []
    seen: set[str] = set()
    for raw in nodes_raw:
        if not isinstance(raw, dict):
            raise ValueError("node must be an object")
        node_id = str(raw.get("id", ""))
        if not node_id or node_id in {"0", "1"}:
            raise ValueError(f"invalid node id {node_id!r}")
        if node_id in seen:
            raise ValueError(f"duplicate node id {node_id!r}")
        seen.add(node_id)
        group = str(raw["group"]) if raw.get("group") is not None else None
        if group is not None and any(not part for part in group.split("/")):
            raise ValueError(f"invalid group path {group!r}")
        width = float(raw.get("width", 120))
        height = float(raw.get("height", 60))
        if (
            not math.isfinite(width)
            or not math.isfinite(height)
            or min(width, height) <= 0
        ):
            raise ValueError(f"node {node_id!r} must have positive finite dimensions")
        nodes.append(
            Node(
                id=node_id,
                label=str(raw.get("label", node_id)),
                style=str(raw.get("style", DEFAULT_NODE_STYLE)),
                width=width,
                height=height,
                group=group,
            )
        )

    edges: list[Edge] = []
    for index, raw in enumerate(edges_raw):
        if not isinstance(raw, dict):
            raise ValueError("edge must be an object")
        source = str(raw.get("source", ""))
        target = str(raw.get("target", ""))
        if source not in seen or target not in seen:
            raise ValueError(f"edge {index} references missing endpoint")
        edge_id = str(raw.get("id", f"edge-{index}-{source}-{target}"))
        edges.append(
            Edge(
                id=edge_id,
                source=source,
                target=target,
                label=str(raw.get("label", "")),
            )
        )
    _validate_cell_ids(nodes, edges)
    return graph_direction, nodes, edges


def _validate_cell_ids(nodes: list[Node], edges: list[Edge]) -> None:
    identities = [(f"node {node.id!r}", _cell_id(node.id)) for node in nodes]
    identities.extend((f"edge {edge.id!r}", _cell_id(edge.id)) for edge in edges)
    groups = {
        "/".join(parts[: index + 1])
        for node in nodes
        if node.group
        for parts in [node.group.split("/")]
        for index in range(len(parts))
    }
    identities.extend(
        (f"group {group!r}", _cell_id("group-" + group)) for group in groups
    )
    seen: dict[str, str] = {}
    for identity, cell_id in identities:
        if cell_id in seen:
            raise ValueError(
                f"cell id collision between {seen[cell_id]} and {identity}: {cell_id!r}"
            )
        seen[cell_id] = identity


def _dot_source(direction: str, nodes: list[Node], edges: list[Edge]) -> str:
    lines = [
        "digraph G {",
        f"  rankdir={direction};",
        "  graph [splines=ortho, nodesep=0.55, ranksep=0.75];",
        "  node [shape=box, fixedsize=true];",
    ]
    children, direct_nodes = _group_tree(nodes)
    for node in sorted(direct_nodes.get("", []), key=lambda item: item.id):
        lines.append(_dot_node(node))
    lines.extend(_dot_group_lines("", children, direct_nodes, indent="  "))
    for edge in edges:
        label = f" [label={_dot_quote(edge.label)}]" if edge.label else ""
        lines.append(
            f"  {_dot_quote(edge.source)} -> {_dot_quote(edge.target)}{label};"
        )
    lines.append("}")
    return "\n".join(lines)


def _group_tree(
    nodes: list[Node],
) -> tuple[dict[str, set[str]], dict[str, list[Node]]]:
    children: dict[str, set[str]] = {"": set()}
    direct_nodes: dict[str, list[Node]] = {"": []}
    for node in nodes:
        if not node.group:
            direct_nodes[""].append(node)
            continue
        parts = node.group.split("/")
        for index in range(len(parts)):
            parent = "/".join(parts[:index])
            group = "/".join(parts[: index + 1])
            children.setdefault(parent, set()).add(group)
            children.setdefault(group, set())
            direct_nodes.setdefault(group, [])
        direct_nodes[node.group].append(node)
    return children, direct_nodes


def _dot_group_lines(
    parent: str,
    children: dict[str, set[str]],
    direct_nodes: dict[str, list[Node]],
    *,
    indent: str,
) -> list[str]:
    lines: list[str] = []
    for group in sorted(children.get(parent, set())):
        cluster_id = "cluster_" + _cell_id(group)
        lines.append(f"{indent}subgraph {_dot_quote(cluster_id)} {{")
        lines.append(f"{indent}  label={_dot_quote(group.split('/')[-1])};")
        lines.append(f"{indent}  margin=24;")
        for node in sorted(direct_nodes.get(group, []), key=lambda item: item.id):
            lines.append(f"{indent}  {_dot_node(node).strip()}")
        lines.extend(
            _dot_group_lines(group, children, direct_nodes, indent=indent + "  ")
        )
        lines.append(f"{indent}}}")
    return lines


def _dot_node(node: Node) -> str:
    return (
        f"  {_dot_quote(node.id)} "
        f"[label={_dot_quote(node.label)}, width={node.width / PX_PER_INCH:.3f}, "
        f"height={node.height / PX_PER_INCH:.3f}];"
    )


def _run_dot(dot: str, source: str) -> PlainLayout:
    with tempfile.TemporaryDirectory(prefix="drawio-cli-dot-") as tmp:
        dot_path = Path(tmp) / "graph.dot"
        dot_path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [dot, "-Tplain", str(dot_path)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    if result.returncode != 0:
        raise RuntimeError(f"dot failed: {result.stderr.strip()}")
    return _parse_plain(result.stdout)


def _parse_plain(text: str) -> PlainLayout:
    graph_height = 0.0
    nodes: dict[str, PlainNode] = {}
    edges: dict[tuple[str, str], list[PlainEdge]] = {}
    for line in text.splitlines():
        parts = shlex.split(line)
        if not parts:
            continue
        if parts[0] == "graph" and len(parts) >= 4:
            graph_height = float(parts[3]) * PX_PER_INCH
        elif parts[0] == "node" and len(parts) >= 6:
            node_id = parts[1]
            x = float(parts[2]) * PX_PER_INCH
            y = graph_height - float(parts[3]) * PX_PER_INCH
            width = float(parts[4]) * PX_PER_INCH
            height = float(parts[5]) * PX_PER_INCH
            nodes[node_id] = PlainNode(x=x - width / 2, y=y - height / 2)
        elif parts[0] == "edge" and len(parts) >= 6:
            tail = parts[1]
            head = parts[2]
            count = int(parts[3])
            coords = parts[4 : 4 + count * 2]
            points = [
                (
                    float(coords[i]) * PX_PER_INCH,
                    graph_height - float(coords[i + 1]) * PX_PER_INCH,
                )
                for i in range(0, len(coords), 2)
            ]
            edges.setdefault((tail, head), []).append(PlainEdge(points=points))
    return PlainLayout(nodes=nodes, edges=edges)


def _geometry(x: int, y: int, width: int, height: int) -> str:
    return f'<mxGeometry x="{x}" y="{y}" width="{width}" height="{height}" as="geometry" />'


def _render_xml(nodes: list[Node], edges: list[Edge], plain: PlainLayout) -> bytes:
    group_depth = max(
        (node.group.count("/") + 1 for node in nodes if node.group), default=0
    )
    offset_x = (
        40
        + 30 * group_depth
        - min((node.x for node in plain.nodes.values()), default=0)
    )
    offset_y = (
        40
        + 60 * group_depth
        - min((node.y for node in plain.nodes.values()), default=0)
    )
    node_boxes: dict[str, tuple[int, int, int, int]] = {}
    for node in nodes:
        placed = plain.nodes[node.id]
        node_boxes[node.id] = (
            _snap(placed.x + offset_x),
            _snap(placed.y + offset_y),
            max(GRID, _snap(node.width)),
            max(GRID, _snap(node.height)),
        )

    groups = _group_boxes(nodes, node_boxes)
    content_boxes = [*node_boxes.values(), *groups.values()]
    page_width = max([x + w + 40 for x, _, w, _ in content_boxes] + [850])
    page_height = max([y + h + 40 for _, y, _, h in content_boxes] + [1100])
    lines = [
        '<mxfile host="offline">',
        '  <diagram id="page-1" name="Page-1">',
        f'    <mxGraphModel dx="0" dy="0" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{page_width}" pageHeight="{page_height}" math="0" shadow="0">',
        "      <root>",
        '        <mxCell id="0" />',
        '        <mxCell id="1" parent="0" />',
    ]
    for group, box in sorted(groups.items(), key=lambda item: item[0].count("/")):
        x, y, width, height = box
        parent_group = group.rsplit("/", 1)[0] if "/" in group else None
        parent = _cell_id("group-" + parent_group) if parent_group else "1"
        if parent_group:
            parent_box = groups[parent_group]
            x -= parent_box[0]
            y -= parent_box[1]
        lines.append(
            f'        <mxCell id="{html.escape(_cell_id("group-" + group))}" value="{html.escape(group.split("/")[-1])}" style="{GROUP_STYLE}" vertex="1" parent="{html.escape(parent)}">'
        )
        lines.append(f"          {_geometry(x, y, width, height)}")
        lines.append("        </mxCell>")
    for node in nodes:
        x, y, width, height = node_boxes[node.id]
        parent = _cell_id("group-" + node.group) if node.group else "1"
        if node.group:
            group_box = groups[node.group]
            x -= group_box[0]
            y -= group_box[1]
        lines.append(
            f'        <mxCell id="{html.escape(_cell_id(node.id))}" value="{html.escape(node.label)}" style="{html.escape(node.style)}" vertex="1" parent="{html.escape(parent)}">'
        )
        lines.append(f"          {_geometry(x, y, width, height)}")
        lines.append("        </mxCell>")
    edge_offsets: dict[tuple[str, str], int] = {}
    for edge in edges:
        waypoints = ""
        key = (edge.source, edge.target)
        offset = edge_offsets.get(key, 0)
        edge_offsets[key] = offset + 1
        plain_edges = plain.edges.get(key, [])
        if offset < len(plain_edges):
            points = [
                (_snap(x + offset_x), _snap(y + offset_y))
                for x, y in plain_edges[offset].points[1:-1]
            ]
            if points:
                waypoint_lines = ['            <Array as="points">']
                waypoint_lines.extend(
                    f'              <mxPoint x="{x}" y="{y}" />' for x, y in points
                )
                waypoint_lines.append("            </Array>")
                waypoints = "\n" + "\n".join(waypoint_lines) + "\n          "
        lines.append(
            f'        <mxCell id="{html.escape(_cell_id(edge.id))}" value="{html.escape(edge.label)}" style="{EDGE_STYLE}" edge="1" parent="1" source="{html.escape(_cell_id(edge.source))}" target="{html.escape(_cell_id(edge.target))}">'
        )
        lines.append(
            f'          <mxGeometry relative="1" as="geometry">{waypoints}</mxGeometry>'
        )
        lines.append("        </mxCell>")
    lines.extend(["      </root>", "    </mxGraphModel>", "  </diagram>", "</mxfile>"])
    return ("\n".join(lines) + "\n").encode()


def _group_boxes(
    nodes: list[Node], boxes: dict[str, tuple[int, int, int, int]]
) -> dict[str, tuple[int, int, int, int]]:
    result: dict[str, tuple[int, int, int, int]] = {}
    padding = 30
    title = 30
    groups: set[str] = set()
    for node in nodes:
        if node.group:
            parts = node.group.split("/")
            groups.update("/".join(parts[: idx + 1]) for idx in range(len(parts)))
    for group in sorted(groups, key=lambda item: item.count("/"), reverse=True):
        content_boxes = [boxes[node.id] for node in nodes if node.group == group]
        content_boxes.extend(
            box
            for child, box in result.items()
            if "/" in child and child.rsplit("/", 1)[0] == group
        )
        if not content_boxes:
            continue
        min_x = min(x for x, _, _, _ in content_boxes) - padding
        min_y = min(y for _, y, _, _ in content_boxes) - padding - title
        max_x = max(x + w for x, _, w, _ in content_boxes) + padding
        max_y = max(y + h for _, y, _, h in content_boxes) + padding
        result[group] = (
            _snap(min_x),
            _snap(min_y),
            _snap(max_x - min_x),
            _snap(max_y - min_y),
        )
    return result


def layout_graph(
    graph_json: Path,
    output: Path,
    *,
    direction: str | None = None,
    dot: str | None = None,
) -> None:
    if os.path.lexists(output):
        raise ValueError(f"layout output already exists: {output}")
    graph_direction, nodes, edges = _load_graph(graph_json, direction)
    dot_bin = dot or os.environ.get("DRAWIO_CLI_DOT", "dot")
    plain = _run_dot(dot_bin, _dot_source(graph_direction, nodes, edges))
    data = _render_xml(nodes, edges, plain)
    # Validate through parser after bytes are complete; failure leaves destination untouched.
    with tempfile.TemporaryDirectory(prefix="drawio-cli-layout-") as tmp:
        candidate = Path(tmp) / "candidate.drawio"
        candidate.write_bytes(data)
        result = validate_document(DrawioDocument.from_file(candidate))
        if result.errors:
            raise RuntimeError(
                "layout produced invalid drawio: " + "; ".join(result.errors)
            )
    try:
        atomic_write_bytes(output, data, overwrite=False)
    except FileExistsError as exc:
        raise ValueError(f"layout output already exists: {output}") from exc
