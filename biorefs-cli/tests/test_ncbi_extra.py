# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, cast

import pytest

from biorefs_cli.commands import ncbi
from biorefs_cli.errors import CLIError

if TYPE_CHECKING:
    from biorefs_cli.ncbi_client import NCBIClient


def ns(**kwargs: object) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_ncbi_markdown_renderers_cover_human_paths() -> None:
    search = ncbi.markdown_search(
        {
            "db": "pubmed",
            "query": "BRCA1",
            "count": 2,
            "ids": ["1", "2"],
            "query_translation": "BRCA1[All Fields]",
            "history": {"query_key": "1"},
        },
    )
    summary = ncbi.markdown_summary(
        {
            "db": "gene",
            "records": [
                {"uid": "672", "name": "BRCA1"},
                {"id": "1", "description": "fallback description"},
            ],
        },
    )
    empty_summary = ncbi.markdown_summary({"db": "gene", "records": []})
    fetch = ncbi.markdown_fetch(
        "<Entrezgene-Set />",
        ns(db="gene", id="672", format="xml"),
    )
    link = ncbi.markdown_link(
        {
            "dbfrom": "gene",
            "db": "pubmed",
            "id": "672",
            "linksets": [
                {"link_name": "gene_pubmed", "ids": ["1", "2", "3"]},
                "bad",
            ],
        },
    )
    empty_link = ncbi.markdown_link({"dbfrom": "gene", "db": "pubmed", "id": "672"})

    assert "NCBI Search" in search
    assert "Query translation" in search
    assert "BRCA1" in search
    assert "BRCA1" in summary
    assert "No records" in empty_summary
    assert "```xml" in fetch
    assert "gene_pubmed" in link
    assert "No links" in empty_link


def test_ncbi_write_output_paths(capsys: pytest.CaptureFixture[str]) -> None:
    ncbi.write_output(
        ns(ncbi_command="search", json=True),
        {"source": "ncbi", "ids": ["1"]},
    )
    ncbi.write_output(
        ns(ncbi_command="search", json=False),
        {"db": "pubmed", "query": "BRCA1", "count": 1, "ids": ["1"]},
    )
    ncbi.write_output(
        ns(ncbi_command="summary", json=False),
        {"db": "gene", "records": [{"uid": "672", "name": "BRCA1"}]},
    )
    ncbi.write_output(
        ns(ncbi_command="link", json=False),
        {"dbfrom": "gene", "db": "pubmed", "id": "672", "linksets": []},
    )
    ncbi.write_fetch_output(ns(format="fasta", raw=True), ">seq\nAA\n")
    ncbi.write_fetch_output(ns(format="json", raw=False), {"content": "x"})
    ncbi.write_fetch_output(ns(db="gene", id="672", format="text", raw=False), "text")

    captured = capsys.readouterr().out
    assert '"ids"' in captured
    assert "NCBI Search" in captured
    assert "NCBI Summary" in captured
    assert "NCBI Links" in captured
    assert ">seq" in captured
    assert '"content"' in captured
    assert "NCBI Fetch" in captured


def test_ncbi_parse_edge_helpers_and_unknown_command() -> None:
    assert ncbi.parse_elink_linksets({"linksets": "bad"}, "gene", "pubmed") == []
    assert (
        ncbi.parse_elink_linksets(
            {"linksets": [{"ids": ["1"], "linksetdbs": "bad"}]},
            "gene",
            "pubmed",
        )
        == []
    )
    assert ncbi.parse_elink_group({}, ["1", "2"], "gene", "pubmed") == {
        "source_ids": ["1", "2"],
        "target_db": "pubmed",
        "link_name": "",
        "ids": [],
        "links": [],
    }
    assert ncbi.parse_elink_links("bad") == []
    assert ncbi.str_or_none(None) is None
    assert ncbi.int_or_none("not-int") is None
    with pytest.raises(CLIError, match="unknown ncbi command"):
        ncbi.execute(ns(ncbi_command="unknown"), client=cast("NCBIClient", object()))
