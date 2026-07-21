from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import __version__, xmlsafe
from .atomic import same_file
from .document import DrawioDocument, DrawioError, Sha256Conflict, element_to_text
from .layout import layout_graph
from .render import render_diagram
from .shapes import load_index, search_shapes
from .validate import validate_document

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEGATIVE_RESULT = 3
EXIT_CONFLICT = 4
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")


class CliError(RuntimeError):
    def __init__(self, message: str, exit_code: int = EXIT_ERROR) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _sha256(value: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("must be a 64-digit hexadecimal SHA-256")
    return value.lower()


def _json_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-j", "--json", action="store_true", help="print JSON")


def _selector_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--page-id", metavar="ID", help="select page by stable ID")
    group.add_argument("--page-name", metavar="NAME", help="select page by name")
    group.add_argument(
        "--page-index",
        type=_nonnegative_int,
        metavar="N",
        help="select page by zero-based index",
    )


def _page_model(doc: DrawioDocument, ns: argparse.Namespace) -> ET.Element:
    return doc.page_model(
        page_id=getattr(ns, "page_id", None),
        page_name=getattr(ns, "page_name", None),
        page_index=getattr(ns, "page_index", None),
    )


def _cmd_pages(ns: argparse.Namespace) -> int:
    doc = DrawioDocument.from_file(Path(ns.file))
    payload = {"sha256": doc.sha256, "pages": doc.pages()}
    print(
        json.dumps(payload, indent=2, ensure_ascii=False)
        if ns.json
        else _format_pages(payload)
    )
    return EXIT_OK


def _format_pages(payload: dict[str, Any]) -> str:
    pages = payload["pages"]
    assert isinstance(pages, list)
    lines = [f"sha256 {payload['sha256']}"]
    for page in pages:
        assert isinstance(page, dict)
        lines.append(
            f"{page['index']}: id={page['id']} name={page['name']} compressed={page['compressed']}"
        )
    return "\n".join(lines)


def _cmd_page_get(ns: argparse.Namespace) -> int:
    source = Path(ns.file)
    output = Path(ns.output) if ns.output else None
    if output is not None and same_file(source, output):
        raise CliError("page output must not overwrite source file")
    doc = DrawioDocument.from_file(source)
    text = element_to_text(_page_model(doc, ns))
    if output is not None:
        output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return EXIT_OK


def _cmd_page_replace(ns: argparse.Namespace) -> int:
    try:
        model = xmlsafe.parse(ns.input).getroot()
        if model is None:
            raise CliError("input model is empty")
    except ET.ParseError as exc:
        raise CliError(f"cannot parse input model: {exc}") from exc
    new_hash = DrawioDocument.replace_page_atomic(
        Path(ns.file),
        model,
        expect_sha256=ns.expect_sha256,
        page_id=getattr(ns, "page_id", None),
        page_name=getattr(ns, "page_name", None),
        page_index=getattr(ns, "page_index", None),
    )
    payload = {"sha256": new_hash}
    print(json.dumps(payload, indent=2) if ns.json else f"sha256 {new_hash}")
    return EXIT_OK


def _cmd_validate(ns: argparse.Namespace) -> int:
    result = validate_document(DrawioDocument.from_file(Path(ns.file)))
    if ns.json:
        print(
            json.dumps({"errors": result.errors, "warnings": result.warnings}, indent=2)
        )
    else:
        for warning in result.warnings:
            print(f"warning: {warning}")
        for error in result.errors:
            print(f"error: {error}")
        print(f"{len(result.errors)} error(s), {len(result.warnings)} warning(s)")
    if result.errors or (ns.strict and result.warnings):
        return EXIT_NEGATIVE_RESULT
    return EXIT_OK


def _cmd_shapes(ns: argparse.Namespace) -> int:
    index_value = ns.index or os.environ.get("DRAWIO_CLI_INDEX")
    if not index_value:
        raise CliError("shape index path required via --index or DRAWIO_CLI_INDEX")
    result = search_shapes(
        load_index(Path(index_value)),
        ns.query,
        limit=ns.limit,
        library=ns.library,
        kind=ns.kind,
        fuzzy=ns.fuzzy,
    )
    if not result.entries:
        raise CliError(f"no shapes matched {ns.query!r}", EXIT_NEGATIVE_RESULT)
    if ns.json:
        print(
            json.dumps(
                {
                    "strong": result.strong,
                    "results": [entry.to_json() for entry in result.entries],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        suffix = "strong" if result.strong else "fuzzy"
        print(f"match-quality: {suffix}")
        for entry in result.entries:
            print(
                f"{entry.title} ({entry.width}x{entry.height}) [{','.join(entry.libraries)}]\n  {entry.style}"
            )
    return EXIT_OK


def _report_output(ns: argparse.Namespace) -> None:
    if ns.json:
        print(json.dumps({"output": str(ns.output)}, indent=2))
    else:
        print(f"wrote {ns.output}", file=sys.stderr)


def _cmd_layout(ns: argparse.Namespace) -> int:
    layout_graph(Path(ns.graph), Path(ns.output), direction=ns.direction, dot=ns.dot)
    _report_output(ns)
    return EXIT_OK


def _cmd_render(ns: argparse.Namespace) -> int:
    render_diagram(
        Path(ns.file),
        Path(ns.output),
        fmt=ns.format,
        page_index=ns.page_index,
        width=ns.width,
        transparent=ns.transparent,
        drawio=ns.drawio,
    )
    _report_output(ns)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drawio-cli",
        description="Create, inspect, validate, lay out, search, and render draw.io files offline.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    pages = sub.add_parser(
        "list-pages",
        aliases=["pages"],
        help="list pages and document hash",
        description="List draw.io pages and raw-file SHA-256.",
    )
    pages.add_argument("file", metavar="FILE", help="draw.io document")
    _json_arg(pages)
    pages.set_defaults(func=_cmd_pages)

    page_get = sub.add_parser(
        "get-page",
        aliases=["page-get"],
        help="extract one page as mxGraphModel XML",
        description="Extract one page as standalone uncompressed mxGraphModel XML.",
    )
    page_get.add_argument("file", metavar="FILE", help="draw.io document")
    _selector_args(page_get)
    page_get.add_argument(
        "--output", metavar="FILE", help="write XML to file instead of stdout"
    )
    page_get.set_defaults(func=_cmd_page_get)

    page_replace = sub.add_parser(
        "replace-page",
        aliases=["page-replace"],
        help="replace one page with SHA-256 guard",
        description="Replace one page only when source SHA-256 still matches.",
    )
    page_replace.add_argument("file", metavar="FILE", help="draw.io document")
    _selector_args(page_replace)
    page_replace.add_argument(
        "--input", required=True, metavar="FILE", help="replacement mxGraphModel XML"
    )
    page_replace.add_argument(
        "--expect-sha256",
        required=True,
        type=_sha256,
        metavar="HASH",
        help="expected raw-file SHA-256 from list-pages",
    )
    _json_arg(page_replace)
    page_replace.set_defaults(func=_cmd_page_replace)

    validate = sub.add_parser(
        "validate",
        help="validate draw.io structure",
        description="Validate page IDs, cell references, geometry, overlap, and routes.",
    )
    validate.add_argument("file", metavar="FILE", help="draw.io document")
    validate.add_argument(
        "--strict", action="store_true", help="treat warnings as validation failure"
    )
    _json_arg(validate)
    validate.set_defaults(func=_cmd_validate)

    shapes = sub.add_parser(
        "search-shapes",
        aliases=["shapes"],
        help="search local draw.io shape index",
        description="Search packaged draw.io shapes without network access.",
    )
    shapes.add_argument("query", metavar="QUERY", help="space-separated search terms")
    shapes.add_argument(
        "--index",
        metavar="FILE",
        help="shape index path; defaults to DRAWIO_CLI_INDEX",
    )
    shapes.add_argument(
        "--limit", type=_positive_int, default=10, metavar="N", help="maximum results"
    )
    shapes.add_argument("--library", metavar="NAME", help="filter by draw.io library")
    shapes.add_argument(
        "--kind",
        choices=["vertex", "edge", "template"],
        help="filter by shape representation",
    )
    shapes.add_argument(
        "--fuzzy",
        action="store_true",
        help="allow scored OR fallback when all-term search fails",
    )
    _json_arg(shapes)
    shapes.set_defaults(func=_cmd_shapes)

    layout = sub.add_parser(
        "layout",
        help="lay out graph JSON with Graphviz",
        description="Create a new single-page draw.io file from graph JSON.",
    )
    layout.add_argument("graph", metavar="GRAPH.json", help="graph JSON input")
    layout.add_argument(
        "--output", required=True, metavar="FILE", help="new draw.io output file"
    )
    layout.add_argument(
        "--direction",
        choices=["TB", "LR"],
        help="override top-to-bottom or left-to-right direction",
    )
    layout.add_argument(
        "--dot", metavar="PATH", help="override Graphviz dot executable for diagnostics"
    )
    _json_arg(layout)
    layout.set_defaults(func=_cmd_layout)

    render = sub.add_parser(
        "render",
        help="export via draw.io Desktop CLI",
        description="Export a validated draw.io file to PNG, SVG, or PDF.",
    )
    render.add_argument("file", metavar="FILE", help="draw.io source document")
    render.add_argument(
        "--format",
        required=True,
        choices=["png", "svg", "pdf"],
        help="export format",
    )
    render.add_argument(
        "--output", required=True, metavar="FILE", help="derived output file"
    )
    render.add_argument(
        "--page-index",
        type=_nonnegative_int,
        metavar="N",
        help="zero-based page index",
    )
    render.add_argument(
        "--width", type=_positive_int, metavar="PX", help="output width in pixels"
    )
    render.add_argument(
        "--transparent",
        action="store_true",
        help="use transparent background; PNG only",
    )
    render.add_argument(
        "--drawio", metavar="PATH", help="override draw.io executable for diagnostics"
    )
    _json_arg(render)
    render.set_defaults(func=_cmd_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    try:
        return int(ns.func(ns))
    except Sha256Conflict as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFLICT
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except (DrawioError, RuntimeError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
