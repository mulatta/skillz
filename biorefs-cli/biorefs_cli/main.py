# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from biorefs_cli import __version__
from biorefs_cli.commands import (
    assay,
    compound,
    gene,
    ncbi,
    nucleotide,
    openalex,
    paper,
    protein,
    setup,
    structure,
    uniprot,
)
from biorefs_cli.errors import CLIError

if TYPE_CHECKING:
    from collections.abc import Sequence

COMMAND_MODULES = (
    setup,
    paper,
    gene,
    nucleotide,
    protein,
    uniprot,
    structure,
    compound,
    assay,
    openalex,
    ncbi,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="biorefs-cli")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module in COMMAND_MODULES:
        module.register(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        return int(handler(args))
    except CLIError as exc:
        print(f"error: {exc.safe_message}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
