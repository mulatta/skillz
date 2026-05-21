"""Assay command placeholders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from biorefs_cli.errors import NotImplementedCommandError

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("assay", help="PubChem BioAssay workflows")
    assay_subcommands = parser.add_subparsers(dest="assay_command", required=True)
    search = assay_subcommands.add_parser("search", help="Search assays")
    search.add_argument("--target")
    search.add_argument("--compound")
    search.add_argument("--limit", type=int)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)
    fetch = assay_subcommands.add_parser("fetch", help="Fetch assay record")
    fetch.add_argument("--aid")
    fetch.add_argument("--include")
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    msg = "assay"
    raise NotImplementedCommandError(msg, args.assay_command)
