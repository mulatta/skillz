"""OpenAlex command placeholders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from biorefs_cli.errors import NotImplementedCommandError

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("openalex", help="OpenAlex enrichment workflows")
    openalex_subcommands = parser.add_subparsers(dest="openalex_command", required=True)

    work = openalex_subcommands.add_parser("work", help="Fetch OpenAlex work")
    work.add_argument("--doi")
    work.add_argument("--pmid")
    work.add_argument("--pmcid")
    work.add_argument("--openalex-id")
    work.add_argument("--json", action="store_true")
    work.set_defaults(handler=handle)

    oa = openalex_subcommands.add_parser("oa", help="Fetch OA locations")
    oa.add_argument("--doi")
    oa.add_argument("--pmid")
    oa.add_argument("--pmcid")
    oa.add_argument("--json", action="store_true")
    oa.set_defaults(handler=handle)

    graph = openalex_subcommands.add_parser("graph", help="Fetch citation graph")
    graph.add_argument("--doi")
    graph.add_argument("--pmid")
    graph.add_argument("--openalex-id")
    graph.add_argument("--direction", choices=("references", "cited-by", "related"))
    graph.add_argument("--limit", type=int)
    graph.add_argument("--json", action="store_true")
    graph.set_defaults(handler=handle)

    trends = openalex_subcommands.add_parser("trends", help="Fetch OpenAlex trends")
    trends.add_argument("query")
    trends.add_argument(
        "--group-by", choices=("publication-year", "oa-status", "country", "topic")
    )
    trends.add_argument("--since", metavar="YEAR")
    trends.add_argument("--until", metavar="YEAR")
    trends.add_argument("--json", action="store_true")
    trends.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    command = "openalex"
    raise NotImplementedCommandError(command, args.openalex_command)
