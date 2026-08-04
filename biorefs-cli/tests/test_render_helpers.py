# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, cast

import pytest
from biorefs_cli.commands import assay, compound, gene, nucleotide, openalex, protein
from biorefs_cli.errors import CLIError, HTTPError, RateLimitError

if TYPE_CHECKING:
    from biorefs_cli.commands.nucleotide import NucleotideSearchResult
    from biorefs_cli.http import JsonObject


def test_gene_markdown_error_and_link_helpers() -> None:
    record: dict[str, object] = {
        "gene_id": "672",
        "official_symbol": "BRCA1",
        "description": "DNA repair",
        "organism": {"scientific_name": "Homo sapiens", "tax_id": "9606"},
        "map_location": "17q21.31",
        "aliases": ["RNF53"],
        "source_urls": ["https://www.ncbi.nlm.nih.gov/gene/672"],
        "summary": "Maintains genome stability.",
        "links": {"pubmed": [{"target_id": "1"}]},
    }
    ambiguous = gene.AmbiguousGeneError("ABC1", [record])

    assert "BRCA1" in gene.search_markdown({"records": [record | {"rank": 1}]})
    assert "pubmed links" in gene.fetch_markdown({"record": record})
    assert "gene_pubmed" in gene.links_markdown(
        {
            "links": [
                {
                    "source_id": "672",
                    "target_db": "pubmed",
                    "target_id": "1",
                    "link_name": "gene_pubmed",
                }
            ]
        }
    )
    candidates = gene.ambiguous_error_payload(ambiguous)["candidates"]
    assert isinstance(candidates, list)
    assert candidates[0]["gene_id"] == "672"
    error = gene.error_payload(CLIError("boom"))["error"]
    assert isinstance(error, dict)
    assert error["message"] == "boom"
    assert gene.link_identifiers("clinvar", "123") == {"clinvar_id": "123"}
    assert gene.link_identifiers("unknown", "123") == {"uid": "123"}
    assert gene.parse_link_targets(None) == []
    with pytest.raises(CLIError):
        gene.parse_link_targets("pubmed,bad")
    with pytest.raises(CLIError):
        gene.candidate_gene_id({})


def test_protein_edge_helpers_and_prints(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(CLIError, match="limit"):
        protein.validate_limit(0)
    with pytest.raises(CLIError, match="limit"):
        protein.validate_limit(protein.MAX_LIMIT + 1)
    with pytest.raises(CLIError, match="unsupported"):
        protein.efetch_format("pdf")
    with pytest.raises(HTTPError, match="missing object"):
        protein.object_field({}, "result")
    with pytest.raises(HTTPError, match="string list"):
        protein.string_list_field({"uids": [1]}, "uids")
    with pytest.raises(HTTPError, match="string"):
        protein.optional_string_field({"caption": []}, "caption")
    with pytest.raises(HTTPError, match="integer"):
        protein.optional_int_field({"slen": "abc"}, "slen")

    assert protein.protein_name("name [Human]", "Human") == "name"
    assert protein.protein_name("name", None) == "name"
    assert protein.display(None) == "-"
    protein.print_search_table({"records": []})
    protein.print_search_table(
        {
            "records": [
                {
                    "accession": "NP_1",
                    "name": "Protein",
                    "organism": "Human",
                    "length": 1,
                    "source_database": "refseq",
                }
            ]
        }
    )
    out = capsys.readouterr().out
    assert "No protein records" in out
    assert "NP_1" in out


def test_nucleotide_edge_helpers_and_prints(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(HTTPError, match="missing result"):
        nucleotide.object_child({}, "result")
    with pytest.raises(CLIError, match="name is required"):
        nucleotide.namespace_str(argparse.Namespace(name=None), "name")
    with pytest.raises(CLIError, match="must be a string"):
        nucleotide.namespace_optional_str(argparse.Namespace(name=1), "name")
    with pytest.raises(CLIError, match="must be an integer"):
        nucleotide.namespace_int(argparse.Namespace(limit="1"), "limit")
    with pytest.raises(CLIError, match="must be boolean"):
        nucleotide.namespace_bool(argparse.Namespace(json="yes"), "json")

    assert nucleotide.string_list(["1", 2, object()]) == ["1", "2"]
    assert nucleotide.optional_str("  ") is None
    assert nucleotide.optional_str(7) == "7"
    assert nucleotide.optional_int("bad") is None
    assert nucleotide.int_or_zero("bad") == 0
    assert nucleotide.first_present_str({"a": "", "b": "x"}, ("a", "b")) == "x"
    assert nucleotide.efetch_format("fasta") == ("fasta", "text")
    assert nucleotide.efetch_format("xml") == (None, "xml")
    nucleotide.print_search_result(cast("NucleotideSearchResult", {"records": []}))
    nucleotide.print_search_result(
        cast(
            "NucleotideSearchResult",
            {
                "records": [
                    {
                        "accession": "NM_1",
                        "uid": "1",
                        "organism": "Human",
                        "molecule_type": "mRNA",
                        "length": 10,
                        "title": "Title",
                    }
                ]
            },
        )
    )
    out = capsys.readouterr().out
    assert "No nucleotide records" in out
    assert "NM_1" in out


def test_openalex_markdown_and_normalizer_edges() -> None:
    work = {
        "kind": "openalex.work",
        "identifiers": {"openalex_id": "W1", "doi": "10.1/x"},
        "work": {
            "title": "Work title",
            "publication_year": 2024,
            "venue": {"display_name": "Journal"},
            "cited_by_count": 5,
            "referenced_works_count": 2,
            "open_access": {"oa_status": "green"},
            "authors": [{"name": "Ada"}],
            "topics": [{"display_name": "Biology"}],
        },
    }
    oa = {
        "kind": "openalex.oa",
        "identifiers": {"pmid": "1"},
        "oa_status": "green",
        "locations": [],
    }
    graph = {
        "kind": "openalex.graph",
        "direction": "references",
        "edges": [],
        "truncated": True,
    }
    trends = {
        "kind": "openalex.trends",
        "query": "BRCA1",
        "rows": [{"key": "2024", "display_name": "2024", "count": 1}],
    }

    assert "Work title" in openalex.format_markdown(cast("JsonObject", work))
    assert "No candidate OA" in openalex.format_markdown(cast("JsonObject", oa))
    assert "No edges" in openalex.format_markdown(cast("JsonObject", graph))
    assert "BRCA1" in openalex.format_markdown(cast("JsonObject", trends))
    assert (
        openalex.format_markdown({"kind": "unknown", "x": 1})
        == "{'kind': 'unknown', 'x': 1}"
    )
    assert openalex.normalize_output_doi("https://doi.org/10.1/X") == "10.1/x"
    assert openalex.normalize_output_doi("bad") is None
    assert (
        openalex.normalize_output_pmid("https://pubmed.ncbi.nlm.nih.gov/123/") == "123"
    )
    assert openalex.normalize_output_pmid("abc") is None
    assert (
        openalex.normalize_output_pmcid(
            "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123/"
        )
        == "PMC123"
    )
    assert openalex.normalize_output_pmcid("abc") is None


def test_compound_render_and_error_helpers() -> None:
    record = {
        "cid": 2244,
        "name": "Aspirin",
        "molecular_formula": "C9H8O4",
        "molecular_weight": 180.16,
        "canonical_smiles": "CC",
        "inchikey": "KEY",
        "synonyms": {"items": ["ASA"]},
        "description": [{"heading": "Description", "text": "Analgesic"}],
    }
    assert "Aspirin" in compound.render_markdown(
        {"type": "compound_search", "records": [record]}
    )
    assert "Synonyms" in compound.render_markdown(
        {"type": "compound_fetch", "record": record}
    )
    assert "No compound candidates" in compound.render_fetch({"status": "not_found"})
    assert "Name is ambiguous" in compound.render_fetch(
        {"status": "ambiguous", "candidates": [record]}
    )
    assert "PMID" in compound.render_markdown(
        {
            "type": "compound_xrefs",
            "xrefs": [{"relation": "xref", "target": "PMID:1", "url": "u"}],
        }
    )
    assert "active" in compound.render_markdown(
        {
            "type": "compound_bioactivity",
            "rows": [{"aid": 1, "outcome": "active", "target": {"name": "T"}}],
        }
    )
    assert "Field" in compound.render_markdown({"type": "unknown", "x": "y"})
    assert compound.normalize_key(" Activity-Outcome ") == "activity_outcome"
    assert compound.error_payload(RateLimitError())["reason"] == "pubchem-rate-limited"
    assert compound.error_payload(HTTPError("network"))["reason"] == "pubchem-network"


def test_assay_render_and_error_helpers() -> None:
    search = {
        "results": [
            {
                "aid": 1,
                "name": "Assay",
                "assay_type": "confirmatory",
                "activity_outcome": "Active",
                "target_hints": [{"gene_symbol": "PARP1"}],
                "source": "PubChem",
            }
        ]
    }
    fetch = {
        "aid": 1,
        "name": "Assay",
        "description": "Description",
        "targets": [
            {"name": "PARP1", "gene_id": "142", "protein_gi": "1", "organism": "Human"}
        ],
        "concise": {"assay_type": "confirmatory"},
        "activity": [
            {
                "sid": "1",
                "cid": "2",
                "outcome": "active",
                "activity_name": "IC50",
                "activity_value": 1,
                "activity_unit": "nM",
            }
        ],
        "activity_summary": {"returned_rows": 1, "total_rows": 2},
    }

    assert "PARP1" in assay.render_search(cast("JsonObject", search))
    assert "No assays found" in assay.render_search({"results": []})
    rendered = assay.render_fetch(cast("JsonObject", fetch))
    assert "Description" in rendered
    assert "Targets" in rendered
    assert "Concise metadata" in rendered
    assert "Returned 1 of 2" in rendered
    assert assay.normalize_outcome(2) == "active"
    assert assay.normalize_outcome("Inactive") == "inactive"
    assert assay.normalize_outcome(None) == ""
    with pytest.raises(HTTPError, match="boom"):
        assay.handle_http_error(HTTPError("boom"), json_output=False)
