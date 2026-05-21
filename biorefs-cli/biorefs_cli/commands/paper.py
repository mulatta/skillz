"""Paper command placeholders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from biorefs_cli.errors import NotImplementedCommandError

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("paper", help="PubMed/PMC paper workflows")
    paper_subcommands = parser.add_subparsers(dest="paper_command", required=True)

    search = paper_subcommands.add_parser("search", help="Search papers")
    search.add_argument("query")
    search.add_argument(
        "--source", choices=("pubmed", "europepmc", "openalex", "crossref")
    )
    search.add_argument("--since", metavar="YEAR")
    search.add_argument("--until", metavar="YEAR")
    search.add_argument("--type")
    search.add_argument("--limit", type=int)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    fetch = paper_subcommands.add_parser("fetch", help="Fetch paper metadata")
    fetch.add_argument("--pmid")
    fetch.add_argument("--pmcid")
    fetch.add_argument("--doi")
    fetch.add_argument("--include")
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)

    fulltext = paper_subcommands.add_parser(
        "fulltext", help="Fetch open-access full text"
    )
    fulltext.add_argument("--pmid")
    fulltext.add_argument("--pmcid")
    fulltext.add_argument("--doi")
    fulltext.add_argument("--sections")
    fulltext.add_argument("--source", choices=("pmc", "europepmc", "auto"))
    fulltext.add_argument("--json", action="store_true")
    fulltext.set_defaults(handler=handle)

    convert = paper_subcommands.add_parser("convert", help="Convert paper identifiers")
    convert.add_argument("--pmid")
    convert.add_argument("--pmcid")
    convert.add_argument("--doi")
    convert.add_argument("--json", action="store_true")
    convert.set_defaults(handler=handle)

    cite = paper_subcommands.add_parser("cite", help="Export citations")
    cite.add_argument("--pmid")
    cite.add_argument("--pmcid")
    cite.add_argument("--doi")
    cite.add_argument("--format", choices=("markdown", "bibtex", "ris", "json"))
    cite.add_argument("--strict", action="store_true")
    cite.set_defaults(handler=handle)

    related = paper_subcommands.add_parser("related", help="Find related papers")
    related.add_argument("--pmid")
    related.add_argument("--doi")
    related.add_argument("--mode", choices=("similar", "references", "cited-by"))
    related.add_argument("--limit", type=int)
    related.add_argument("--json", action="store_true")
    related.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    command = "paper"
    raise NotImplementedCommandError(command, args.paper_command)
