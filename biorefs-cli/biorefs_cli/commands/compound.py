"""Compound command placeholders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from biorefs_cli.errors import NotImplementedCommandError

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("compound", help="PubChem compound workflows")
    compound_subcommands = parser.add_subparsers(dest="compound_command", required=True)

    search = compound_subcommands.add_parser("search", help="Search compounds")
    search.add_argument("query")
    search.add_argument(
        "--type", choices=("name", "cid", "smiles", "inchikey", "formula")
    )
    search.add_argument("--limit", type=int)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    fetch = compound_subcommands.add_parser("fetch", help="Fetch compound record")
    fetch.add_argument("--cid")
    fetch.add_argument("--name")
    fetch.add_argument("--include")
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)

    xrefs = compound_subcommands.add_parser(
        "xrefs", help="Fetch compound cross-references"
    )
    xrefs.add_argument("--cid")
    xrefs.add_argument("--to")
    xrefs.add_argument("--json", action="store_true")
    xrefs.set_defaults(handler=handle)

    bioactivity = compound_subcommands.add_parser(
        "bioactivity", help="Fetch compound bioactivity"
    )
    bioactivity.add_argument("--cid")
    bioactivity.add_argument("--target")
    bioactivity.add_argument("--active-only", action="store_true")
    bioactivity.add_argument("--limit", type=int)
    bioactivity.add_argument("--json", action="store_true")
    bioactivity.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    command = "compound"
    raise NotImplementedCommandError(command, args.compound_command)
