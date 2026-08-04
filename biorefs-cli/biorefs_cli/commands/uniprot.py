# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""UniProtKB command implementation.

Identifier-first protein annotation: canonical accession, function, entity
cross-references, and curated literature links. Structure files are out of
scope; PDB cross-references are surfaced as pointers (id, method, resolution)
that downstream structural-biology tooling consumes. UniProt is the seam where
a protein name resolves to PDB accessions, NCBI Gene/RefSeq, and PubMed IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import quote, urlencode

from biorefs_cli.config import Config, load_config
from biorefs_cli.errors import CLIError, HTTPError
from biorefs_cli.http import HttpClient, JsonObject
from biorefs_cli.identifiers import normalize_uniprot_accession as normalize_accession
from biorefs_cli.jsonshape import object_or_none, optional_int, optional_str
from biorefs_cli.output import display, markdown_table, print_json

if TYPE_CHECKING:
    import argparse

UNIPROT_BASE_URL = "https://rest.uniprot.org"
USER_AGENT = "biorefs-cli/0.1 (https://github.com/mulatta/skillz)"
RATE_LIMIT_SOURCE = "uniprot"
DEFAULT_LIMIT = 25
MAX_LIMIT = 500

SEARCH_FIELDS = (
    "accession,id,reviewed,protein_name,gene_names,organism_name,organism_id,length"
)
# --include section -> extra UniProt return fields requested for that section.
INCLUDE_FIELDS = {
    "function": ("cc_function",),
    "xrefs": ("xref_pdb", "xref_geneid", "xref_refseq", "xref_ensembl"),
    "literature": ("lit_pubmed_id",),
}
INCLUDE_CHOICES = tuple(INCLUDE_FIELDS)
DEFAULT_INCLUDE = ("function", "xrefs", "literature")
# Entity cross-references worth surfacing for the paper/gene linking graph.
ENTITY_XREF_DBS = ("GeneID", "RefSeq", "Ensembl")


class UniProtBackend(Protocol):
    def search(self, params: dict[str, str]) -> JsonObject: ...

    def entry(self, accession: str, fields: str) -> JsonObject: ...

    def fasta(self, accession: str) -> str: ...


class UniProtClient:
    def __init__(self, *, config: Config, http: HttpClient | None = None) -> None:
        self.config = config
        self.http = http or HttpClient(timeout_seconds=config.timeout_seconds)

    def search(self, params: dict[str, str]) -> JsonObject:
        url = f"{UNIPROT_BASE_URL}/uniprotkb/search?{urlencode(params)}"
        return self.http.get_json(
            url, headers={"User-Agent": USER_AGENT}, rate_limit_source=RATE_LIMIT_SOURCE
        )

    def entry(self, accession: str, fields: str) -> JsonObject:
        path_id = quote(accession, safe="")
        params = urlencode({"format": "json", "fields": fields})
        url = f"{UNIPROT_BASE_URL}/uniprotkb/{path_id}?{params}"
        return self.http.get_json(
            url, headers={"User-Agent": USER_AGENT}, rate_limit_source=RATE_LIMIT_SOURCE
        )

    def fasta(self, accession: str) -> str:
        path_id = quote(accession, safe="")
        url = f"{UNIPROT_BASE_URL}/uniprotkb/{path_id}.fasta"
        response = self.http.get(
            url, headers={"User-Agent": USER_AGENT}, rate_limit_source=RATE_LIMIT_SOURCE
        )
        try:
            return response.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            msg = "UniProt returned non-UTF-8 FASTA record"
            raise HTTPError(msg, status=response.status) from exc


@dataclass(frozen=True, slots=True)
class PdbStructure:
    id: str
    method: str | None
    resolution: str | None
    chains: str | None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "method": self.method,
            "resolution": self.resolution,
            "chains": self.chains,
        }


@dataclass(frozen=True, slots=True)
class UniProtRecord:
    accession: str
    entry_name: str | None
    reviewed: bool
    protein_name: str | None
    genes: list[str]
    organism: str | None
    tax_id: int | None
    length: int | None
    function: list[str]
    pdb: list[PdbStructure]
    literature_pmids: list[str]
    xrefs: dict[str, list[str]]

    def to_json_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source": "uniprot",
            "accession": self.accession,
            "entry_name": self.entry_name,
            "reviewed": self.reviewed,
            "protein_name": self.protein_name,
            "genes": self.genes,
            "organism": self.organism,
            "tax_id": self.tax_id,
            "length": self.length,
            "provenance": provenance(),
        }
        if self.function:
            payload["function"] = self.function
        if self.pdb:
            payload["pdb"] = [structure.to_json_dict() for structure in self.pdb]
        if self.literature_pmids:
            payload["literature_pmids"] = self.literature_pmids
        if self.xrefs:
            payload["xrefs"] = self.xrefs
        return payload


class UniProtService:
    def __init__(self, backend: UniProtBackend) -> None:
        self.backend = backend

    def search(
        self,
        query: str,
        *,
        taxon: str | None,
        reviewed: bool,
        limit: int,
    ) -> dict[str, object]:
        validate_limit(limit)
        term = build_search_query(query, taxon=taxon, reviewed=reviewed)
        payload = cast(
            "dict[str, object]",
            self.backend.search(
                {
                    "query": term,
                    "format": "json",
                    "size": str(limit),
                    "fields": SEARCH_FIELDS,
                }
            ),
        )
        records = [parse_entry(entry) for entry in result_entries(payload)]
        return {
            "source": "uniprot",
            "query": query.strip(),
            "query_term": term,
            "size": limit,
            "records": [record.to_json_dict() for record in records],
            "provenance": provenance(),
        }

    def fetch_summary(
        self, accession: str, *, include: tuple[str, ...]
    ) -> dict[str, object]:
        normalized = normalize_accession(accession)
        fields = build_fields(include)
        payload = cast("dict[str, object]", self.backend.entry(normalized, fields))
        record = parse_entry(payload)
        result = record.to_json_dict()
        result["requested_accession"] = normalized
        return result

    def fetch_fasta(self, accession: str) -> dict[str, object]:
        normalized = normalize_accession(accession)
        content = self.backend.fasta(normalized)
        return {
            "source": "uniprot",
            "accession": normalized,
            "format": "fasta",
            "content": content,
            "provenance": provenance(),
        }


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("uniprot", help="UniProtKB protein annotation")
    uniprot_subcommands = parser.add_subparsers(dest="uniprot_command", required=True)

    search = uniprot_subcommands.add_parser("search", help="Search UniProtKB entries")
    search.add_argument("query")
    search.add_argument("--taxon", metavar="TAXID")
    search.add_argument(
        "--reviewed", action="store_true", help="Restrict to Swiss-Prot entries"
    )
    search.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    fetch = uniprot_subcommands.add_parser("fetch", help="Fetch a UniProtKB entry")
    fetch.add_argument("--accession")
    fetch.add_argument(
        "--format", choices=("summary", "fasta", "json"), default="summary"
    )
    fetch.add_argument(
        "--include",
        metavar="SECTIONS",
        help=f"comma list of {','.join(INCLUDE_CHOICES)} (default: all)",
    )
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    config = load_config()
    service = UniProtService(UniProtClient(config=config))
    if args.uniprot_command == "search":
        return handle_search(args, service)
    if args.uniprot_command == "fetch":
        return handle_fetch(args, service)
    msg = "unknown uniprot subcommand"
    raise CLIError(msg, exit_code=2)


def handle_search(args: argparse.Namespace, service: UniProtService) -> int:
    limit = DEFAULT_LIMIT if args.limit is None else args.limit
    result = service.search(
        args.query, taxon=args.taxon, reviewed=args.reviewed, limit=limit
    )
    if args.json:
        print_json(result)
    else:
        print_search_table(result)
    return 0


def handle_fetch(args: argparse.Namespace, service: UniProtService) -> int:
    if not args.accession:
        msg = "uniprot fetch requires --accession"
        raise CLIError(msg, exit_code=2)
    output_format = args.format or "summary"
    if output_format in {"summary", "json"}:
        include = parse_include(args.include)
        print_json(service.fetch_summary(args.accession, include=include))
        return 0
    result = service.fetch_fasta(args.accession)
    if args.json:
        print_json(result)
    else:
        print(str(result["content"]), end="")
    return 0


def build_search_query(query: str, *, taxon: str | None, reviewed: bool) -> str:
    stripped = query.strip()
    if not stripped:
        msg = "uniprot search requires QUERY"
        raise CLIError(msg, exit_code=2)
    term = stripped
    if taxon is not None:
        taxon_id = taxon.strip()
        if not taxon_id.isdecimal():
            msg = "--taxon must be an NCBI taxonomy ID"
            raise CLIError(msg, exit_code=2)
        term = f"{term} AND organism_id:{taxon_id}"
    if reviewed:
        term = f"{term} AND reviewed:true"
    return term


def parse_include(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_INCLUDE
    sections = [item.strip() for item in raw.split(",") if item.strip()]
    invalid = [item for item in sections if item not in INCLUDE_FIELDS]
    if invalid:
        msg = f"unknown --include section(s): {', '.join(invalid)}"
        raise CLIError(msg, exit_code=2)
    return tuple(sections)


def build_fields(include: tuple[str, ...]) -> str:
    fields = list(SEARCH_FIELDS.split(","))
    for section in include:
        for field in INCLUDE_FIELDS.get(section, ()):
            if field not in fields:
                fields.append(field)
    return ",".join(fields)


def validate_limit(limit: int) -> None:
    if limit < 1:
        msg = "--limit must be at least 1"
        raise CLIError(msg, exit_code=2)
    if limit > MAX_LIMIT:
        msg = f"--limit must be at most {MAX_LIMIT}"
        raise CLIError(msg, exit_code=2)


def result_entries(payload: dict[str, object]) -> list[dict[str, object]]:
    results = payload.get("results")
    if results is None:
        return []
    if not isinstance(results, list):
        msg = "UniProt search response field results must be a list"
        raise HTTPError(msg)
    return [entry for entry in results if isinstance(entry, dict)]


def parse_entry(entry: dict[str, object]) -> UniProtRecord:
    accession = optional_str(entry, "primaryAccession")
    if accession is None:
        msg = "UniProt entry missing primaryAccession"
        raise HTTPError(msg)
    organism = object_or_none(entry, "organism")
    return UniProtRecord(
        accession=accession,
        entry_name=optional_str(entry, "uniProtkbId"),
        reviewed=is_reviewed(entry),
        protein_name=protein_name(entry),
        genes=gene_names(entry),
        organism=optional_str(organism, "scientificName") if organism else None,
        tax_id=optional_int(organism, "taxonId") if organism else None,
        length=sequence_length(entry),
        function=function_texts(entry),
        pdb=pdb_structures(entry),
        literature_pmids=literature_pmids(entry),
        xrefs=entity_xrefs(entry),
    )


def is_reviewed(entry: dict[str, object]) -> bool:
    entry_type = optional_str(entry, "entryType") or ""
    return "unreviewed" not in entry_type.lower() and "reviewed" in entry_type.lower()


def protein_name(entry: dict[str, object]) -> str | None:
    description = object_or_none(entry, "proteinDescription")
    if description is None:
        return None
    recommended = object_or_none(description, "recommendedName")
    if recommended is not None:
        name = named_value(recommended, "fullName")
        if name is not None:
            return name
    for key in ("submissionNames", "alternativeNames"):
        names = description.get(key)
        if isinstance(names, list):
            for item in names:
                if isinstance(item, dict):
                    name = named_value(item, "fullName")
                    if name is not None:
                        return name
    return None


def named_value(payload: dict[str, object], key: str) -> str | None:
    nested = object_or_none(payload, key)
    if nested is None:
        return None
    return optional_str(nested, "value")


def gene_names(entry: dict[str, object]) -> list[str]:
    genes = entry.get("genes")
    if not isinstance(genes, list):
        return []
    names: list[str] = []
    for gene in genes:
        if not isinstance(gene, dict):
            continue
        name = named_value(gene, "geneName")
        if name is not None:
            names.append(name)
    return names


def sequence_length(entry: dict[str, object]) -> int | None:
    sequence = object_or_none(entry, "sequence")
    if sequence is None:
        return None
    return optional_int(sequence, "length")


def function_texts(entry: dict[str, object]) -> list[str]:
    comments = entry.get("comments")
    if not isinstance(comments, list):
        return []
    texts: list[str] = []
    for comment in comments:
        if not isinstance(comment, dict) or comment.get("commentType") != "FUNCTION":
            continue
        raw_texts = comment.get("texts")
        if not isinstance(raw_texts, list):
            continue
        for item in raw_texts:
            if isinstance(item, dict):
                value = optional_str(item, "value")
                if value is not None:
                    texts.append(value)
    return texts


def pdb_structures(entry: dict[str, object]) -> list[PdbStructure]:
    structures: list[PdbStructure] = []
    for xref in cross_references(entry):
        if xref.get("database") != "PDB":
            continue
        identifier = optional_str(xref, "id")
        if identifier is None:
            continue
        props = property_map(xref)
        structures.append(
            PdbStructure(
                id=identifier,
                method=props.get("Method"),
                resolution=props.get("Resolution"),
                chains=props.get("Chains"),
            )
        )
    return structures


def literature_pmids(entry: dict[str, object]) -> list[str]:
    references = entry.get("references")
    if not isinstance(references, list):
        return []
    pmids: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if not isinstance(reference, dict):
            continue
        citation = object_or_none(reference, "citation")
        if citation is None:
            continue
        cross_refs = citation.get("citationCrossReferences")
        if not isinstance(cross_refs, list):
            continue
        for cross_ref in cross_refs:
            if not isinstance(cross_ref, dict) or cross_ref.get("database") != "PubMed":
                continue
            pmid = optional_str(cross_ref, "id")
            if pmid is not None and pmid not in seen:
                seen.add(pmid)
                pmids.append(pmid)
    return pmids


def entity_xrefs(entry: dict[str, object]) -> dict[str, list[str]]:
    xrefs: dict[str, list[str]] = {}
    for xref in cross_references(entry):
        database = xref.get("database")
        if database not in ENTITY_XREF_DBS:
            continue
        identifier = optional_str(xref, "id")
        if identifier is None:
            continue
        bucket = xrefs.setdefault(cast("str", database), [])
        if identifier not in bucket:
            bucket.append(identifier)
    return xrefs


def cross_references(entry: dict[str, object]) -> list[dict[str, object]]:
    xrefs = entry.get("uniProtKBCrossReferences")
    if not isinstance(xrefs, list):
        return []
    return [xref for xref in xrefs if isinstance(xref, dict)]


def property_map(xref: dict[str, object]) -> dict[str, str]:
    props = xref.get("properties")
    if not isinstance(props, list):
        return {}
    result: dict[str, str] = {}
    for prop in props:
        if not isinstance(prop, dict):
            continue
        key = optional_str(prop, "key")
        value = optional_str(prop, "value")
        if key is not None and value is not None and value != "-":
            result[key] = value
    return result


def provenance() -> dict[str, object]:
    return {
        "provider": "uniprot",
        "endpoint": "uniprotkb",
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def print_search_table(result: dict[str, object]) -> None:
    raw_records = result.get("records")
    records = raw_records if isinstance(raw_records, list) else []
    if not records:
        print("No UniProt entries found.")
        return
    rows = []
    for record in records:
        if not isinstance(record, dict):
            continue
        genes = record.get("genes")
        gene_label = ", ".join(genes) if isinstance(genes, list) and genes else "-"
        rows.append(
            (
                display(record.get("accession")),
                "reviewed" if record.get("reviewed") else "unreviewed",
                gene_label,
                display(record.get("protein_name")),
                display(record.get("organism")),
                display(record.get("length")),
            )
        )
    print(
        markdown_table(
            ("Accession", "Status", "Genes", "Protein", "Organism", "Length"),
            rows,
        )
    )
