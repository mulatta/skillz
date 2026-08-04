# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""NCBI Nucleotide commands."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict, cast

from biorefs_cli.config import load_config
from biorefs_cli.errors import CLIError, HTTPError
from biorefs_cli.ncbi_client import NCBIClient
from biorefs_cli.output import markdown_table, print_json

if TYPE_CHECKING:
    import argparse


NUCCORE_DB = "nuccore"
DEFAULT_LIMIT = 20
MAX_LIMIT = 500
ACCESSION_RE = re.compile(r"^[A-Z]{1,6}_?[A-Z0-9]{5,12}(?:\.\d+)?$")

NucleotideKind = Literal["mrna", "lncrna", "genomic", "refseq"]
FetchFormat = Literal["summary", "fasta", "genbank", "xml", "json"]
TextFetchFormat = Literal["fasta", "genbank", "xml"]

KIND_FILTERS: dict[NucleotideKind, str] = {
    "mrna": '(mRNA[Filter] OR biomol_mRNA[PROP] OR "messenger RNA"[Title])',
    "lncrna": '(lncRNA[Title] OR "long non-coding RNA"[Title] OR "long non coding RNA"[Title] OR biomol_ncRNA[PROP])',
    "genomic": '(biomol_genomic[PROP] OR "genomic DNA"[Title] OR chromosome[Title] OR "complete genome"[Title])',
    "refseq": "srcdb_refseq[PROP]",
}


class Provenance(TypedDict):
    endpoint: str
    database: str


class NucleotideSummary(TypedDict):
    source: str
    source_db: str
    uid: str
    gi: str | None
    accession: str | None
    title: str | None
    organism: str | None
    molecule_type: str | None
    length: int | None
    provenance: Provenance
    raw: NotRequired[dict[str, object]]


class NucleotideSearchResult(TypedDict):
    source: str
    source_db: str
    query: str
    translated_query: str | None
    count: int
    retmax: int
    ids: list[str]
    records: list[NucleotideSummary]


class FetchTextResult(TypedDict):
    source: str
    source_db: str
    accession: str
    uid: str
    format: str
    content: str


@dataclass(frozen=True, slots=True)
class ResolvedAccession:
    accession: str
    uid: str


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("nucleotide", help="NCBI nucleotide workflows")
    nucleotide_subcommands = parser.add_subparsers(
        dest="nucleotide_command",
        required=True,
    )

    search = nucleotide_subcommands.add_parser(
        "search",
        help="Search nucleotide records",
    )
    search.add_argument("query")
    search.add_argument("--taxon")
    search.add_argument("--kind", choices=("mrna", "lncrna", "genomic", "refseq"))
    search.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    fetch = nucleotide_subcommands.add_parser("fetch", help="Fetch nucleotide record")
    fetch.add_argument("--accession")
    fetch.add_argument(
        "--format",
        choices=("summary", "fasta", "genbank", "xml", "json"),
        default="summary",
    )
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    subcommand = namespace_str(args, "nucleotide_command")
    if subcommand == "fetch" and getattr(args, "accession", None) is None:
        msg = "nucleotide fetch requires --accession"
        raise CLIError(msg, exit_code=2)

    client = build_client()
    if subcommand == "search":
        return handle_search(args, client)
    if subcommand == "fetch":
        return handle_fetch(args, client)
    msg = f"unsupported nucleotide command: {subcommand}"
    raise CLIError(msg, exit_code=2)


def build_client() -> NCBIClient:
    config = load_config()
    if not config.email:
        msg = "NCBI email is required; run biorefs-cli setup config --email EMAIL"
        raise CLIError(msg, exit_code=2)
    return NCBIClient.from_config(config)


def handle_search(args: argparse.Namespace, client: NCBIClient) -> int:
    result = search_nucleotide(
        client,
        query=namespace_str(args, "query"),
        taxon=namespace_optional_str(args, "taxon"),
        kind=cast("NucleotideKind | None", namespace_optional_str(args, "kind")),
        limit=namespace_int(args, "limit"),
    )
    if namespace_bool(args, "json"):
        print_json(result)
    else:
        print_search_result(result)
    return 0


def handle_fetch(args: argparse.Namespace, client: NCBIClient) -> int:
    fetch_format = cast("FetchFormat", namespace_str(args, "format"))
    accession = namespace_str(args, "accession")
    if fetch_format in {"summary", "json"}:
        print_json(fetch_nucleotide_summary(client, accession))
        return 0

    text_format = cast("TextFetchFormat", fetch_format)
    result = fetch_nucleotide_text(
        client,
        accession=accession,
        fetch_format=text_format,
    )
    if namespace_bool(args, "json"):
        print_json(result)
    else:
        sys.stdout.write(result["content"])
        if result["content"] and not result["content"].endswith("\n"):
            sys.stdout.write("\n")
    return 0


def validate_limit(limit: int) -> int:
    if limit < 1 or limit > MAX_LIMIT:
        msg = f"limit must be between 1 and {MAX_LIMIT}"
        raise CLIError(msg, exit_code=2)
    return limit


def normalize_accession(accession: str) -> str:
    normalized = accession.strip().upper()
    if not ACCESSION_RE.fullmatch(normalized):
        msg = "accession must look like an NCBI nucleotide accession, e.g. NM_007294.4"
        raise CLIError(msg, exit_code=2)
    return normalized


def build_nucleotide_query(
    query: str,
    *,
    taxon: str | None = None,
    kind: NucleotideKind | None = None,
) -> str:
    base = query.strip()
    if not base:
        msg = "query must not be empty"
        raise CLIError(msg, exit_code=2)
    clauses = [f"({base})"]
    if taxon is not None:
        taxon_value = taxon.strip()
        if not taxon_value.isdigit():
            msg = "taxon must be an NCBI taxonomy ID"
            raise CLIError(msg, exit_code=2)
        clauses.append(f"txid{taxon_value}[Organism:exp]")
    if kind is not None:
        clauses.append(KIND_FILTERS[kind])
    return " AND ".join(clauses)


def accession_query(accession: str) -> str:
    normalized = normalize_accession(accession)
    return f"{normalized}[Accession]"


def search_nucleotide(
    client: NCBIClient,
    *,
    query: str,
    taxon: str | None,
    kind: NucleotideKind | None,
    limit: int,
) -> NucleotideSearchResult:
    retmax = validate_limit(limit)
    term = build_nucleotide_query(query, taxon=taxon, kind=kind)
    search = cast(
        "dict[str, object]",
        client.request_json(
            "esearch",
            {
                "db": NUCCORE_DB,
                "term": term,
                "retmode": "json",
                "retmax": retmax,
            },
        ),
    )
    search_result = object_child(search, "esearchresult")
    ids = string_list(search_result.get("idlist"))
    count = int_or_zero(search_result.get("count"))
    translated_query = optional_str(search_result.get("querytranslation"))
    records = parse_nucleotide_summaries(fetch_summaries(client, ids))
    return {
        "source": "ncbi",
        "source_db": NUCCORE_DB,
        "query": term,
        "translated_query": translated_query,
        "count": count,
        "retmax": retmax,
        "ids": ids,
        "records": records,
    }


def fetch_summaries(client: NCBIClient, ids: list[str]) -> dict[str, object]:
    if not ids:
        return {"result": {"uids": []}}
    return cast(
        "dict[str, object]",
        client.request_json(
            "esummary",
            {
                "db": NUCCORE_DB,
                "id": ",".join(ids),
                "retmode": "json",
            },
        ),
    )


def resolve_accession(client: NCBIClient, accession: str) -> ResolvedAccession:
    normalized = normalize_accession(accession)
    search = cast(
        "dict[str, object]",
        client.request_json(
            "esearch",
            {
                "db": NUCCORE_DB,
                "term": accession_query(normalized),
                "retmode": "json",
                "retmax": 1,
            },
        ),
    )
    search_result = object_child(search, "esearchresult")
    ids = string_list(search_result.get("idlist"))
    if not ids:
        msg = f"no NCBI nucleotide record found for {normalized}"
        raise CLIError(msg)
    return ResolvedAccession(accession=normalized, uid=ids[0])


def fetch_nucleotide_summary(client: NCBIClient, accession: str) -> NucleotideSummary:
    resolved = resolve_accession(client, accession)
    summaries = parse_nucleotide_summaries(fetch_summaries(client, [resolved.uid]))
    if not summaries:
        msg = f"no NCBI summary found for {resolved.accession}"
        raise CLIError(msg)
    summary = summaries[0]
    if summary["accession"] is None:
        summary["accession"] = resolved.accession
    return summary


def fetch_nucleotide_text(
    client: NCBIClient,
    *,
    accession: str,
    fetch_format: TextFetchFormat,
) -> FetchTextResult:
    resolved = resolve_accession(client, accession)
    rettype, retmode = efetch_format(fetch_format)
    params: dict[str, str | int] = {
        "db": NUCCORE_DB,
        "id": resolved.uid,
        "retmode": retmode,
    }
    if rettype is not None:
        params["rettype"] = rettype
    response = client.http.get(
        client.eutils_url("efetch", params),
        rate_limit_source=client.rate_limit_source(),
    )
    try:
        content = response.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = "NCBI returned non-UTF-8 content"
        raise HTTPError(msg, status=response.status) from exc
    return {
        "source": "ncbi",
        "source_db": NUCCORE_DB,
        "accession": resolved.accession,
        "uid": resolved.uid,
        "format": fetch_format,
        "content": content,
    }


def parse_nucleotide_summaries(payload: dict[str, object]) -> list[NucleotideSummary]:
    result = object_child(payload, "result")
    uids = string_list(result.get("uids"))
    records: list[NucleotideSummary] = []
    for uid in uids:
        raw_record = result.get(uid)
        if not isinstance(raw_record, dict):
            continue
        record = cast("dict[str, object]", raw_record)
        records.append(parse_nucleotide_summary(uid, record))
    return records


def parse_nucleotide_summary(uid: str, record: dict[str, object]) -> NucleotideSummary:
    accession = first_present_str(record, ("accessionversion", "caption", "accession"))
    molecule_type = first_present_str(
        record,
        ("biomol", "molecule_type", "moltype", "geneticcode"),
    )
    return {
        "source": "ncbi",
        "source_db": NUCCORE_DB,
        "uid": uid,
        "gi": optional_str(record.get("gi")),
        "accession": accession,
        "title": optional_str(record.get("title")),
        "organism": optional_str(record.get("organism")),
        "molecule_type": molecule_type,
        "length": optional_int(record.get("slen")),
        "provenance": {"endpoint": "esummary", "database": NUCCORE_DB},
    }


def efetch_format(fetch_format: TextFetchFormat) -> tuple[str | None, str]:
    if fetch_format == "fasta":
        return "fasta", "text"
    if fetch_format == "genbank":
        return "gb", "text"
    return None, "xml"


def print_search_result(result: NucleotideSearchResult) -> None:
    if not result["records"]:
        print("No nucleotide records found.")
        return
    rows = [
        (
            record["accession"] or record["uid"],
            record["organism"] or "",
            record["molecule_type"] or "",
            record["length"] or "",
            record["title"] or "",
        )
        for record in result["records"]
    ]
    print(markdown_table(("accession", "organism", "type", "length", "title"), rows))


def object_child(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        msg = f"NCBI response missing {key} object"
        raise HTTPError(msg)
    return cast("dict[str, object]", value)


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, int):
            result.append(str(item))
    return result


def optional_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, int):
        return str(value)
    return None


def optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def int_or_zero(value: object) -> int:
    parsed = optional_int(value)
    return parsed or 0


def first_present_str(record: dict[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = optional_str(record.get(key))
        if value is not None:
            return value
    return None


def namespace_str(args: argparse.Namespace, name: str) -> str:
    value = getattr(args, name)
    if not isinstance(value, str):
        msg = f"{name} is required"
        raise CLIError(msg, exit_code=2)
    return value


def namespace_optional_str(args: argparse.Namespace, name: str) -> str | None:
    value = getattr(args, name)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{name} must be a string"
        raise CLIError(msg, exit_code=2)
    return value


def namespace_int(args: argparse.Namespace, name: str) -> int:
    value = getattr(args, name)
    if not isinstance(value, int):
        msg = f"{name} must be an integer"
        raise CLIError(msg, exit_code=2)
    return value


def namespace_bool(args: argparse.Namespace, name: str) -> bool:
    value = getattr(args, name)
    if not isinstance(value, bool):
        msg = f"{name} must be boolean"
        raise CLIError(msg, exit_code=2)
    return value
