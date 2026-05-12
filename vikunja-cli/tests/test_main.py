from __future__ import annotations

from vikunja_cli.main import _build_parser


def test_task_update_parser_accepts_title() -> None:
    ns = _build_parser().parse_args(["task", "update", "5", "--title", "Renamed"])

    assert ns.command == "task"
    assert ns.subcmd == "update"
    assert ns.task == "5"
    assert ns.title == "Renamed"
