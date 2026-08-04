# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from miniflux_cli.main import build_parser


def test_parse_list_entries_core_agent_command() -> None:
    args = build_parser().parse_args(
        ["list", "entries", "--starred", "--category", "notification", "--json"]
    )

    assert args.command == "list"
    assert args.resource == "entries"
    assert args.starred is True
    assert args.category == "notification"
    assert args.json is True


def test_parse_show_entry() -> None:
    args = build_parser().parse_args(["show", "entry", "123"])

    assert args.command == "show"
    assert args.resource == "entry"
    assert args.entry_id == 123


def test_parse_list_enclosures() -> None:
    args = build_parser().parse_args(["list", "enclosures", "123", "--json"])

    assert args.command == "list"
    assert args.resource == "enclosures"
    assert args.entry_id == 123
    assert args.json is True


def test_parse_fetch_enclosure() -> None:
    args = build_parser().parse_args(
        ["fetch", "enclosure", "123", "0", "--output-dir", "/tmp/miniflux"]
    )

    assert args.command == "fetch"
    assert args.resource == "enclosure"
    assert args.entry_id == 123
    assert args.idx == 0
    assert args.output_dir == "/tmp/miniflux"
