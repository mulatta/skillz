"""Gene command placeholders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from biorefs_cli.errors import NotImplementedCommandError

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("gene", help="NCBI Gene workflows")
    gene_subcommands = parser.add_subparsers(dest="gene_command", required=True)

    search = gene_subcommands.add_parser("search", help="Search genes")
    search.add_argument("query")
    search.add_argument("--taxon")
    search.add_argument("--limit", type=int)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    fetch = gene_subcommands.add_parser("fetch", help="Fetch gene record")
    fetch.add_argument("--gene-id")
    fetch.add_argument("--symbol")
    fetch.add_argument("--taxon")
    fetch.add_argument("--links")
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)

    links = gene_subcommands.add_parser("links", help="Fetch gene links")
    links.add_argument("--gene-id")
    links.add_argument("--to", choices=("pubmed", "protein", "nucleotide", "clinvar"))
    links.add_argument("--json", action="store_true")
    links.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    command = "gene"
    raise NotImplementedCommandError(command, args.gene_command)
