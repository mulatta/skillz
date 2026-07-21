from __future__ import annotations

import copy
import math
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass

from .document import DrawioDocument

RESERVED = {"0", "1"}


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]
    warnings: list[str]


def _rect(cell: ET.Element) -> tuple[float, float, float, float] | None:
    geom = cell.find("mxGeometry")
    if geom is None:
        return None
    try:
        return (
            float(geom.get("x", "0")),
            float(geom.get("y", "0")),
            float(geom.get("width", "nan")),
            float(geom.get("height", "nan")),
        )
    except ValueError:
        return None


def _nonfinite(values: Iterable[float]) -> bool:
    return any(not math.isfinite(value) for value in values)


def _is_edge_label(cell: ET.Element) -> bool:
    if "edgeLabel" in (cell.get("style") or ""):
        return True
    geom = cell.find("mxGeometry")
    return geom is not None and geom.get("relative") == "1"


def _overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _style_num(style: str, key: str) -> float | None:
    for part in style.split(";"):
        if part.startswith(key + "="):
            try:
                return float(part.split("=", 1)[1])
            except ValueError:
                return None
    return None


def _abs_rect(
    cell: ET.Element, by_id: dict[str, ET.Element]
) -> tuple[float, float, float, float] | None:
    base = _rect(cell)
    if base is None or _nonfinite(base):
        return None
    x, y, width, height = base
    parent = cell.get("parent")
    seen: set[str] = set()
    while parent and parent in by_id and parent not in seen:
        seen.add(parent)
        parent_cell = by_id[parent]
        if parent_cell.get("vertex") == "1":
            parent_rect = _rect(parent_cell)
            if parent_rect is not None and not _nonfinite(parent_rect):
                x += parent_rect[0]
                y += parent_rect[1]
        parent = parent_cell.get("parent")
    return (x, y, width, height)


def _endpoint(
    edge: ET.Element, end: str, by_id: dict[str, ET.Element]
) -> tuple[float, float] | None:
    vertex_id = edge.get(end)
    if not vertex_id or vertex_id not in by_id:
        return None
    box = _abs_rect(by_id[vertex_id], by_id)
    if box is None:
        return None
    x, y, width, height = box
    style = edge.get("style") or ""
    fx = _style_num(style, "exitX" if end == "source" else "entryX")
    fy = _style_num(style, "exitY" if end == "source" else "entryY")
    return (
        x + (0.5 if fx is None else fx) * width,
        y + (0.5 if fy is None else fy) * height,
    )


def _edge_waypoints(edge: ET.Element) -> list[tuple[float, float]]:
    geom = edge.find("mxGeometry")
    if geom is None:
        return []
    array = geom.find("Array")
    if array is None:
        return []
    points: list[tuple[float, float]] = []
    for point in array.findall("mxPoint"):
        with suppress(ValueError):
            points.append((float(point.get("x", "")), float(point.get("y", ""))))
    return points


def _edge_route(
    edge: ET.Element, by_id: dict[str, ET.Element]
) -> list[tuple[float, float]] | None:
    waypoints = _edge_waypoints(edge)
    if not waypoints:
        return None
    source = _endpoint(edge, "source", by_id)
    target = _endpoint(edge, "target", by_id)
    if source is None or target is None:
        return None
    return [source, *waypoints, target]


def _orient(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> int:
    value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if abs(value) < 1e-9:
        return 0
    return 1 if value > 0 else -1


def _segments_cross(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> bool:
    o1 = _orient(p1, p2, p3)
    o2 = _orient(p1, p2, p4)
    o3 = _orient(p3, p4, p1)
    o4 = _orient(p3, p4, p2)
    return o1 != o2 and o3 != o4 and 0 not in {o1, o2, o3, o4}


def _point_in_rect(
    point: tuple[float, float], box: tuple[float, float, float, float]
) -> bool:
    x, y, width, height = box
    return x < point[0] < x + width and y < point[1] < y + height


def _route_hits_rect(
    points: list[tuple[float, float]], box: tuple[float, float, float, float]
) -> bool:
    x, y, width, height = box
    corners = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    borders = list(zip(corners, [*corners[1:], corners[0]]))
    for start, end in zip(points, points[1:]):
        if _point_in_rect(start, box) or _point_in_rect(end, box):
            return True
        if any(
            _segments_cross(start, end, border_start, border_end)
            for border_start, border_end in borders
        ):
            return True
    return False


def _routes_cross(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> bool:
    return any(
        _segments_cross(a_start, a_end, b_start, b_end)
        for a_start, a_end in zip(a, a[1:])
        for b_start, b_end in zip(b, b[1:])
    )


def _cells(model: ET.Element) -> list[ET.Element]:
    root = model.find("root")
    if root is None:
        return []
    cells: list[ET.Element] = []
    for child in root:
        if child.tag == "mxCell":
            cells.append(child)
        elif child.tag in {"UserObject", "object"}:
            inner = child.find("mxCell")
            if inner is not None:
                wrapped = copy.deepcopy(inner)
                wrapped.set("id", child.get("id", inner.get("id", "")))
                cells.append(wrapped)
    return cells


def _validate_model(model: ET.Element, page_name: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    cells = _cells(model)
    if not cells:
        errors.append(f"page {page_name!r}: missing root cells")
        return ValidationResult(errors, warnings)

    by_id = _index_cells(cells, errors)
    _validate_roots(by_id, errors)

    parents = {cell.get("parent") for cell in cells if cell.get("parent") is not None}
    for cell in cells:
        _validate_cell(cell, by_id, errors, warnings)

    leaf_boxes = [
        (cell.get("id", ""), cell.get("parent"), _rect(cell))
        for cell in cells
        if cell.get("vertex") == "1"
        and cell.get("id") not in parents
        and not _is_edge_label(cell)
        and _rect(cell) is not None
        and not _nonfinite(_rect(cell) or ())
    ]
    for i, (left_id, left_parent, left_rect) in enumerate(leaf_boxes):
        if left_rect is None:
            continue
        for right_id, right_parent, right_rect in leaf_boxes[i + 1 :]:
            if (
                right_rect is not None
                and left_parent == right_parent
                and _overlap(left_rect, right_rect)
            ):
                warnings.append(f"vertices {left_id!r} and {right_id!r} overlap")

    routed = [
        (cell.get("id", ""), route, {cell.get("source"), cell.get("target")})
        for cell in cells
        if cell.get("edge") == "1"
        for route in [_edge_route(cell, by_id)]
        if route is not None
    ]
    abs_leaf_boxes = [
        (cell.get("id", ""), _abs_rect(cell, by_id))
        for cell in cells
        if cell.get("vertex") == "1"
        and cell.get("id") not in parents
        and not _is_edge_label(cell)
    ]
    for edge_id, points, endpoints in routed:
        for vertex_id, box in abs_leaf_boxes:
            if (
                box is not None
                and vertex_id not in endpoints
                and _route_hits_rect(points, box)
            ):
                warnings.append(f"edge {edge_id!r} routes through vertex {vertex_id!r}")
    for i, (left_id, left_route, _) in enumerate(routed):
        for right_id, right_route, _ in routed[i + 1 :]:
            if _routes_cross(left_route, right_route):
                warnings.append(f"edges {left_id!r} and {right_id!r} cross")

    return ValidationResult(errors, warnings)


def _index_cells(cells: list[ET.Element], errors: list[str]) -> dict[str, ET.Element]:
    by_id: dict[str, ET.Element] = {}
    for cell in cells:
        cell_id = cell.get("id")
        if cell_id is None:
            errors.append("cell missing id")
            continue
        if cell_id in by_id:
            errors.append(f"duplicate id {cell_id!r}")
        by_id[cell_id] = cell
    return by_id


def _validate_roots(by_id: dict[str, ET.Element], errors: list[str]) -> None:
    if "0" not in by_id:
        errors.append("missing root cell '0'")
    layer = by_id.get("1")
    if layer is None or layer.get("parent") != "0":
        errors.append("missing default layer cell '1' with parent '0'")


def _validate_cell(
    cell: ET.Element,
    by_id: dict[str, ET.Element],
    errors: list[str],
    warnings: list[str],
) -> None:
    cell_id = cell.get("id", "")
    parent = cell.get("parent")
    is_vertex = cell.get("vertex") == "1"
    is_edge = cell.get("edge") == "1"
    if parent is not None and parent not in by_id:
        errors.append(f"cell {cell_id!r} parent {parent!r} does not exist")
    for end in ("source", "target"):
        ref = cell.get(end)
        if ref and ref not in by_id:
            errors.append(f"edge {cell_id!r} {end} {ref!r} does not exist")
    if (is_vertex or is_edge) and cell_id in RESERVED:
        errors.append(f"cell {cell_id!r} reuses reserved id 0/1")
    if is_vertex and not _is_edge_label(cell):
        _validate_vertex_geometry(cell_id, cell, errors, warnings)


def _validate_vertex_geometry(
    cell_id: str,
    cell: ET.Element,
    errors: list[str],
    warnings: list[str],
) -> None:
    rect = _rect(cell)
    if rect is None or _nonfinite(rect):
        errors.append(f"vertex {cell_id!r} has missing/invalid geometry")
        return
    x, y, width, height = rect
    if width <= 0 or height <= 0:
        warnings.append(f"vertex {cell_id!r} non-positive size {width:g}x{height:g}")
    if x < 0 or y < 0:
        warnings.append(f"vertex {cell_id!r} negative position ({x:g},{y:g})")
    if x % 10 != 0 or y % 10 != 0:
        warnings.append(f"vertex {cell_id!r} off-grid position ({x:g},{y:g})")


def validate_document(document: DrawioDocument) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    seen_page_ids: set[str] = set()
    seen_names: set[str] = set()
    for page in document.page_objects():
        if page.page_id in seen_page_ids:
            errors.append(f"duplicate page id {page.page_id!r}")
        seen_page_ids.add(page.page_id)
        if page.name in seen_names:
            warnings.append(f"duplicate page name {page.name!r}")
        seen_names.add(page.name)
        try:
            result = _validate_model(page.model(), page.name)
        except ValueError as exc:
            errors.append(f"page {page.name!r}: {exc}")
            continue
        errors.extend(result.errors)
        warnings.extend(result.warnings)
    return ValidationResult(errors, warnings)
