"""Protein command placeholders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from biorefs_cli.errors import NotImplementedCommandError

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("protein", help="NCBI protein workflows")
    protein_subcommands = parser.add_subparsers(dest="protein_command", required=True)

    search = protein_subcommands.add_parser("search", help="Search protein records")
    search.add_argument("query")
    search.add_argument("--taxon")
    search.add_argument("--limit", type=int)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    fetch = protein_subcommands.add_parser("fetch", help="Fetch protein record")
    fetch.add_argument("--accession")
    fetch.add_argument(
        "--format", choices=("summary", "fasta", "genbank", "xml", "json")
    )
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    command = "protein"
    raise NotImplementedCommandError(command, args.protein_command)
