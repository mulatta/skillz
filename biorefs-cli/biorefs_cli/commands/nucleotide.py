"""Nucleotide command placeholders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from biorefs_cli.errors import NotImplementedCommandError

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("nucleotide", help="NCBI nucleotide workflows")
    nucleotide_subcommands = parser.add_subparsers(
        dest="nucleotide_command", required=True
    )

    search = nucleotide_subcommands.add_parser(
        "search", help="Search nucleotide records"
    )
    search.add_argument("query")
    search.add_argument("--taxon")
    search.add_argument("--kind", choices=("mrna", "lncrna", "genomic", "refseq"))
    search.add_argument("--limit", type=int)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    fetch = nucleotide_subcommands.add_parser("fetch", help="Fetch nucleotide record")
    fetch.add_argument("--accession")
    fetch.add_argument(
        "--format", choices=("summary", "fasta", "genbank", "xml", "json")
    )
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    command = "nucleotide"
    raise NotImplementedCommandError(command, args.nucleotide_command)
