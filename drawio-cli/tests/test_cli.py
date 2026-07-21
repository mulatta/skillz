from __future__ import annotations

import json
from pathlib import Path

import pytest
from drawio_cli.cli import build_parser, main
from drawio_cli.document import DrawioDocument, element_to_text

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "argv",
    [
        ["list-pages", "diagram.drawio"],
        ["get-page", "diagram.drawio"],
        [
            "replace-page",
            "diagram.drawio",
            "--input",
            "page.xml",
            "--expect-sha256",
            "0" * 64,
        ],
        ["search-shapes", "lambda"],
        ["open", "diagram.drawio"],
        ["handoff", "diagram.drawio"],
        ["pages", "diagram.drawio"],
        ["page-get", "diagram.drawio"],
        [
            "page-replace",
            "diagram.drawio",
            "--input",
            "page.xml",
            "--expect-sha256",
            "0" * 64,
        ],
        ["shapes", "lambda"],
    ],
)
def test_canonical_commands_and_legacy_aliases_parse(argv: list[str]) -> None:
    build_parser().parse_args(argv)


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["--version"])
    assert raised.value.code == 0
    assert capsys.readouterr().out == "drawio-cli 0.1.0\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["get-page", "diagram.drawio", "--page-index", "-1"],
        ["search-shapes", "lambda", "--limit", "0"],
        ["search-shapes", "lambda", "--kind", "unknown"],
        [
            "render",
            "diagram.drawio",
            "--format",
            "png",
            "--output",
            "out.png",
            "--width",
            "0",
        ],
    ],
)
def test_parser_rejects_invalid_constrained_options(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(argv)
    assert raised.value.code == 2


def test_operational_and_conflict_exit_codes(tmp_path: Path) -> None:
    missing = tmp_path / "missing.drawio"
    assert main(["validate", str(missing)]) == 1

    source = tmp_path / "source.drawio"
    source.write_bytes((FIXTURES / "minimal.drawio").read_bytes())
    model = DrawioDocument.from_file(source).page_model(page_index=0)
    page = tmp_path / "page.xml"
    page.write_text(element_to_text(model))
    assert (
        main(
            [
                "replace-page",
                str(source),
                "--input",
                str(page),
                "--expect-sha256",
                "0" * 64,
            ]
        )
        == 4
    )


def test_layout_schema_error_is_reported_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    graph = tmp_path / "graph.json"
    graph.write_text("[]")

    assert main(["layout", str(graph), "--output", str(tmp_path / "out.drawio")]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: graph JSON must be an object\n"


def test_layout_json_reports_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    graph = tmp_path / "graph.json"
    output = tmp_path / "diagram.drawio"
    graph.write_text(json.dumps({"nodes": [{"id": "api"}]}))

    assert main(["layout", str(graph), "--output", str(output), "-j"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"output": str(output)}
    assert captured.err == ""
