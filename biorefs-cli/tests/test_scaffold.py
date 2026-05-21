from __future__ import annotations

import pytest
from biorefs_cli.main import build_parser, main

TOP_LEVEL_COMMANDS = (
    "setup",
    "paper",
    "gene",
    "nucleotide",
    "protein",
    "compound",
    "assay",
    "openalex",
    "ncbi",
)

SUBCOMMAND_OPTIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "paper": {
        "search": ("--source", "--since", "--until", "--type", "--limit", "--json"),
        "fetch": ("--pmid", "--pmcid", "--doi", "--include", "--json"),
        "fulltext": ("--pmid", "--pmcid", "--doi", "--sections", "--source", "--json"),
        "convert": ("--pmid", "--pmcid", "--doi", "--json"),
        "cite": ("--pmid", "--pmcid", "--doi", "--format", "--strict"),
        "related": ("--pmid", "--doi", "--mode", "--limit", "--json"),
    },
    "gene": {
        "search": ("--taxon", "--limit", "--json"),
        "fetch": ("--gene-id", "--symbol", "--taxon", "--links", "--json"),
        "links": ("--gene-id", "--to", "--json"),
    },
    "nucleotide": {
        "search": ("--taxon", "--kind", "--limit", "--json"),
        "fetch": ("--accession", "--format", "--json"),
    },
    "protein": {
        "search": ("--taxon", "--limit", "--json"),
        "fetch": ("--accession", "--format", "--json"),
    },
    "compound": {
        "search": ("--type", "--limit", "--json"),
        "fetch": ("--cid", "--name", "--include", "--json"),
        "xrefs": ("--cid", "--to", "--json"),
        "bioactivity": ("--cid", "--target", "--active-only", "--limit", "--json"),
    },
    "assay": {
        "search": ("--target", "--compound", "--limit", "--json"),
        "fetch": ("--aid", "--include", "--json"),
    },
    "openalex": {
        "work": ("--doi", "--pmid", "--pmcid", "--openalex-id", "--json"),
        "oa": ("--doi", "--pmid", "--pmcid", "--json"),
        "graph": (
            "--doi",
            "--pmid",
            "--openalex-id",
            "--direction",
            "--limit",
            "--json",
        ),
        "trends": ("--group-by", "--since", "--until", "--json"),
    },
    "ncbi": {
        "search": ("--db", "--query", "--limit", "--use-history", "--json"),
        "summary": ("--db", "--id", "--json"),
        "fetch": ("--db", "--id", "--format", "--raw"),
        "link": ("--dbfrom", "--db", "--id", "--json"),
    },
}

PARSER_CASES: tuple[tuple[str, ...], ...] = (
    (
        "paper",
        "search",
        "BRCA1",
        "--source",
        "pubmed",
        "--since",
        "2020",
        "--until",
        "2024",
        "--type",
        "review",
        "--limit",
        "5",
        "--json",
    ),
    (
        "paper",
        "fetch",
        "--pmid",
        "1",
        "--pmcid",
        "PMC1",
        "--doi",
        "10.1/example",
        "--include",
        "abstract,ids",
        "--json",
    ),
    (
        "paper",
        "fulltext",
        "--pmid",
        "1",
        "--pmcid",
        "PMC1",
        "--doi",
        "10.1/example",
        "--sections",
        "methods",
        "--source",
        "auto",
        "--json",
    ),
    (
        "paper",
        "convert",
        "--pmid",
        "1",
        "--pmcid",
        "PMC1",
        "--doi",
        "10.1/example",
        "--json",
    ),
    (
        "paper",
        "cite",
        "--pmid",
        "1",
        "--pmcid",
        "PMC1",
        "--doi",
        "10.1/example",
        "--format",
        "bibtex",
        "--strict",
    ),
    (
        "paper",
        "related",
        "--pmid",
        "1",
        "--doi",
        "10.1/example",
        "--mode",
        "cited-by",
        "--limit",
        "5",
        "--json",
    ),
    ("gene", "search", "BRCA1", "--taxon", "human", "--limit", "5", "--json"),
    (
        "gene",
        "fetch",
        "--gene-id",
        "672",
        "--symbol",
        "BRCA1",
        "--taxon",
        "9606",
        "--links",
        "pubmed,protein",
        "--json",
    ),
    ("gene", "links", "--gene-id", "672", "--to", "pubmed", "--json"),
    (
        "nucleotide",
        "search",
        "BRCA1",
        "--taxon",
        "9606",
        "--kind",
        "mrna",
        "--limit",
        "5",
        "--json",
    ),
    ("nucleotide", "fetch", "--accession", "NM_007294", "--format", "fasta", "--json"),
    ("protein", "search", "BRCA1", "--taxon", "9606", "--limit", "5", "--json"),
    ("protein", "fetch", "--accession", "NP_009225", "--format", "fasta", "--json"),
    ("compound", "search", "olaparib", "--type", "name", "--limit", "5", "--json"),
    (
        "compound",
        "fetch",
        "--cid",
        "23725625",
        "--include",
        "synonyms,description",
        "--json",
    ),
    ("compound", "xrefs", "--cid", "23725625", "--to", "pubmed,gene", "--json"),
    (
        "compound",
        "bioactivity",
        "--cid",
        "23725625",
        "--target",
        "BRCA1",
        "--active-only",
        "--limit",
        "5",
        "--json",
    ),
    (
        "assay",
        "search",
        "--target",
        "BRCA1",
        "--compound",
        "olaparib",
        "--limit",
        "5",
        "--json",
    ),
    ("assay", "fetch", "--aid", "123", "--include", "description", "--json"),
    (
        "openalex",
        "work",
        "--doi",
        "10.1/example",
        "--pmid",
        "1",
        "--pmcid",
        "PMC1",
        "--openalex-id",
        "W1",
        "--json",
    ),
    (
        "openalex",
        "oa",
        "--doi",
        "10.1/example",
        "--pmid",
        "1",
        "--pmcid",
        "PMC1",
        "--json",
    ),
    (
        "openalex",
        "graph",
        "--doi",
        "10.1/example",
        "--pmid",
        "1",
        "--openalex-id",
        "W1",
        "--direction",
        "references",
        "--limit",
        "5",
        "--json",
    ),
    (
        "openalex",
        "trends",
        "BRCA1",
        "--group-by",
        "publication-year",
        "--since",
        "2020",
        "--until",
        "2024",
        "--json",
    ),
    (
        "ncbi",
        "search",
        "--db",
        "pubmed",
        "--query",
        "BRCA1",
        "--limit",
        "5",
        "--use-history",
        "--json",
    ),
    ("ncbi", "summary", "--db", "gene", "--id", "672", "--json"),
    ("ncbi", "fetch", "--db", "gene", "--id", "672", "--format", "json", "--raw"),
    ("ncbi", "link", "--dbfrom", "gene", "--db", "pubmed", "--id", "672", "--json"),
)


def test_top_level_commands_appear_in_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--help"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    for command in TOP_LEVEL_COMMANDS:
        assert command in captured.out


def test_subcommands_appear_in_help(capsys: pytest.CaptureFixture[str]) -> None:
    for command, subcommands in SUBCOMMAND_OPTIONS.items():
        with pytest.raises(SystemExit) as exc_info:
            build_parser().parse_args([command, "--help"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        for subcommand in subcommands:
            assert subcommand in captured.out


def test_finalized_options_appear_in_subcommand_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for command, subcommands in SUBCOMMAND_OPTIONS.items():
        for subcommand, options in subcommands.items():
            with pytest.raises(SystemExit) as exc_info:
                build_parser().parse_args([command, subcommand, "--help"])

            assert exc_info.value.code == 0
            captured = capsys.readouterr()
            for option in options:
                assert option in captured.out


def test_finalized_placeholder_options_parse() -> None:
    for argv in PARSER_CASES:
        parsed = build_parser().parse_args(argv)

        assert parsed.command == argv[0]


def test_placeholders_exit_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    cases = (
        (("paper", "search", "BRCA1"), "paper search"),
        (("nucleotide", "fetch"), "nucleotide fetch"),
        (("protein", "fetch"), "protein fetch"),
        (("assay", "search"), "assay search"),
        (("openalex", "work"), "openalex work"),
    )
    for argv, message in cases:
        status = main(argv)

        captured = capsys.readouterr()
        assert status == 2
        assert message in captured.err
        assert "Traceback" not in captured.err
