# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""NCBI Protein command implementation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from biorefs_cli.config import load_config
from biorefs_cli.errors import CLIError, ConfigError, HTTPError
from biorefs_cli.jsonshape import retrieved_at
from biorefs_cli.ncbi_client import NCBIClient
from biorefs_cli.output import display, markdown_table, print_json

if TYPE_CHECKING:
    import argparse

    from biorefs_cli.http import HttpResponse, JsonObject

PROTEIN_DB = "protein"
DEFAULT_LIMIT = 20
MAX_LIMIT = 500
ACCESSION_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,39}(?:\.\d+)?$")
SUMMARY_FORMATS = {"summary", "json"}
TEXT_FORMATS = {"fasta", "genbank", "xml"}


class TextHttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> HttpResponse: ...


class ProteinEntrezClient(Protocol):
    @property
    def http(self) -> TextHttpClient: ...

    def request_json(
        self, endpoint: str, params: dict[str, str | int]
    ) -> JsonObject: ...

    def eutils_url(self, endpoint: str, params: dict[str, str | int]) -> str: ...

    def rate_limit_source(self, source: str = "ncbi") -> str: ...


@dataclass(frozen=True, slots=True)
class ProteinRecord:
    uid: str
    accession: str | None
    title: str | None
    name: str | None
    organism: str | None
    length: int | None
    source_database: str | None
    tax_id: int | None

    def to_json_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source": "ncbi",
            "source_db": PROTEIN_DB,
            "uid": self.uid,
            "accession": self.accession,
            "title": self.title,
            "name": self.name,
            "organism": self.organism,
            "length": self.length,
            "source_database": self.source_database,
            "provenance": provenance("esummary"),
        }
        if self.tax_id is not None:
            payload["tax_id"] = self.tax_id
        return payload


class ProteinService:
    def __init__(self, client: ProteinEntrezClient) -> None:
        self.client = client

    def search(
        self,
        query: str,
        *,
        taxon: str | None,
        limit: int,
    ) -> dict[str, object]:
        validate_limit(limit)
        term = build_search_term(query, taxon)
        search_payload = self.esearch(term, limit)
        search_result = object_field(search_payload, "esearchresult")
        ids = string_list_field(search_result, "idlist")
        records = self.summary_records(ids)
        return {
            "source": "ncbi",
            "source_db": PROTEIN_DB,
            "query": query.strip(),
            "query_term": term,
            "count": int_field(search_result, "count"),
            "retmax": limit,
            "ids": ids,
            "records": [record.to_json_dict() for record in records],
            "query_translation": optional_string_field(
                search_result,
                "querytranslation",
            ),
            "provenance": {
                "provider": "ncbi-entrez",
                "endpoints": ["esearch", "esummary"],
                "retrieved_at": retrieved_at(),
            },
        }

    def fetch_summary(self, accession: str) -> dict[str, object]:
        normalized = normalize_accession(accession)
        record_id = self.resolve_accession(normalized)
        records = self.summary_records([record_id])
        if not records:
            msg = f"protein accession not found: {normalized}"
            raise CLIError(msg)
        payload = records[0].to_json_dict()
        payload["requested_accession"] = normalized
        return payload

    def fetch_text(self, accession: str, output_format: str) -> dict[str, object]:
        normalized = normalize_accession(accession)
        record_id = self.resolve_accession(normalized)
        retmode, rettype = efetch_format(output_format)
        params: dict[str, str | int] = {
            "db": PROTEIN_DB,
            "id": record_id,
            "retmode": retmode,
        }
        if rettype is not None:
            params["rettype"] = rettype
        url = self.client.eutils_url("efetch", params)
        response = self.client.http.get(
            url,
            rate_limit_source=self.client.rate_limit_source(),
        )
        try:
            content = response.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            msg = "NCBI returned non-UTF-8 protein record"
            raise HTTPError(msg, status=response.status) from exc
        return {
            "source": "ncbi",
            "source_db": PROTEIN_DB,
            "accession": normalized,
            "uid": record_id,
            "format": output_format,
            "content": content,
            "provenance": {
                "provider": "ncbi-entrez",
                "endpoint": "efetch",
                "retmode": retmode,
                "rettype": rettype,
                "retrieved_at": retrieved_at(),
            },
        }

    def resolve_accession(self, accession: str) -> str:
        normalized = normalize_accession(accession)
        payload = self.esearch(f"{normalized}[Accession]", 1)
        search_result = object_field(payload, "esearchresult")
        ids = string_list_field(search_result, "idlist")
        return ids[0] if ids else normalized

    def esearch(self, term: str, limit: int) -> dict[str, object]:
        return cast(
            "dict[str, object]",
            self.client.request_json(
                "esearch",
                {
                    "db": PROTEIN_DB,
                    "term": term,
                    "retmode": "json",
                    "retmax": limit,
                },
            ),
        )

    def summary_records(self, ids: list[str]) -> list[ProteinRecord]:
        if not ids:
            return []
        payload = cast(
            "dict[str, object]",
            self.client.request_json(
                "esummary",
                {"db": PROTEIN_DB, "id": ",".join(ids), "retmode": "json"},
            ),
        )
        return parse_protein_summaries(payload)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("protein", help="NCBI protein workflows")
    protein_subcommands = parser.add_subparsers(dest="protein_command", required=True)

    search = protein_subcommands.add_parser("search", help="Search protein records")
    search.add_argument("query")
    search.add_argument("--taxon", metavar="TAXID")
    search.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    fetch = protein_subcommands.add_parser("fetch", help="Fetch protein record")
    fetch.add_argument("--accession")
    fetch.add_argument(
        "--format",
        choices=("summary", "fasta", "genbank", "xml", "json"),
        default="summary",
    )
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    validate_args(args)
    config = load_config()
    if not config.email:
        msg = "protein commands require configured email; run biorefs-cli setup --email EMAIL"
        raise ConfigError(msg)
    service = ProteinService(NCBIClient.from_config(config))
    if args.protein_command == "search":
        return handle_search(args, service)
    if args.protein_command == "fetch":
        return handle_fetch(args, service)
    msg = "unknown protein subcommand"
    raise CLIError(msg, exit_code=2)


def validate_args(args: argparse.Namespace) -> None:
    if args.protein_command == "search":
        limit = DEFAULT_LIMIT if args.limit is None else args.limit
        validate_limit(limit)
        build_search_term(args.query, args.taxon)
    if args.protein_command == "fetch" and not args.accession:
        msg = "protein fetch requires --accession"
        raise CLIError(msg, exit_code=2)


def handle_search(args: argparse.Namespace, service: ProteinService) -> int:
    limit = DEFAULT_LIMIT if args.limit is None else args.limit
    result = service.search(args.query, taxon=args.taxon, limit=limit)
    if args.json:
        print_json(result)
    else:
        print_search_table(result)
    return 0


def handle_fetch(args: argparse.Namespace, service: ProteinService) -> int:
    if not args.accession:
        msg = "protein fetch requires --accession"
        raise CLIError(msg, exit_code=2)
    output_format = "summary" if args.format is None else args.format
    if output_format in SUMMARY_FORMATS:
        print_json(service.fetch_summary(args.accession))
        return 0
    if output_format in TEXT_FORMATS:
        result = service.fetch_text(args.accession, output_format)
        if args.json:
            print_json(result)
        else:
            print(str(result["content"]), end="")
        return 0
    msg = "unsupported protein fetch format"
    raise CLIError(msg, exit_code=2)


def build_search_term(query: str, taxon: str | None) -> str:
    stripped = query.strip()
    if not stripped:
        msg = "protein search requires QUERY"
        raise CLIError(msg, exit_code=2)
    if taxon is None:
        return stripped
    taxon_id = taxon.strip()
    if not taxon_id.isdecimal():
        msg = "--taxon must be an NCBI taxonomy ID"
        raise CLIError(msg, exit_code=2)
    return f"({stripped}) AND txid{taxon_id}[Organism:exp]"


def normalize_accession(value: str) -> str:
    accession = value.strip().upper()
    if not accession:
        msg = "accession is required"
        raise CLIError(msg, exit_code=2)
    if (
        accession.endswith("_")
        or "__" in accession
        or not ACCESSION_RE.fullmatch(accession)
    ):
        msg = f"invalid protein accession: {value}"
        raise CLIError(msg, exit_code=2)
    return accession


def validate_limit(limit: int) -> None:
    if limit < 1:
        msg = "--limit must be at least 1"
        raise CLIError(msg, exit_code=2)
    if limit > MAX_LIMIT:
        msg = f"--limit must be at most {MAX_LIMIT}"
        raise CLIError(msg, exit_code=2)


def parse_protein_summaries(payload: dict[str, object]) -> list[ProteinRecord]:
    result = object_field(payload, "result")
    records: list[ProteinRecord] = []
    for uid in string_list_field(result, "uids"):
        docsum = object_field(result, uid)
        records.append(parse_protein_docsum(uid, docsum))
    return records


def parse_protein_docsum(uid: str, docsum: dict[str, object]) -> ProteinRecord:
    title = first_string_field(docsum, ("title", "Title"))
    accession = first_string_field(
        docsum,
        ("accessionversion", "AccessionVersion", "accession", "caption", "Caption"),
    )
    organism = first_string_field(docsum, ("organism", "Organism"))
    length = first_int_field(docsum, ("slen", "Slen", "length", "Length"))
    source_database = first_string_field(
        docsum, ("sourcedb", "SourceDb", "source_database")
    )
    tax_id = first_int_field(docsum, ("taxid", "TaxId", "tax_id"))
    return ProteinRecord(
        uid=first_string_field(docsum, ("uid", "Uid")) or uid,
        accession=accession,
        title=title,
        name=protein_name(title, organism),
        organism=organism,
        length=length,
        source_database=source_database,
        tax_id=tax_id,
    )


def protein_name(title: str | None, organism: str | None) -> str | None:
    if title is None:
        return None
    if organism is None:
        return title
    suffix = f" [{organism}]"
    if title.endswith(suffix):
        return title[: -len(suffix)]
    return title


def efetch_format(output_format: str) -> tuple[str, str | None]:
    if output_format == "fasta":
        return "text", "fasta"
    if output_format == "genbank":
        return "text", "gp"
    if output_format == "xml":
        return "xml", None
    msg = "unsupported protein text format"
    raise CLIError(msg, exit_code=2)


def object_field(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        msg = f"NCBI response missing object field {key}"
        raise HTTPError(msg)
    return cast("dict[str, object]", value)


def string_list_field(payload: dict[str, object], key: str) -> list[str]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f"NCBI response field {key} must be a string list"
        raise HTTPError(msg)
    return value


def optional_string_field(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    msg = f"NCBI response field {key} must be a string"
    raise HTTPError(msg)


# These intentionally differ from jsonshape.optional_*: the NCBI eSummary
# parsers here raise HTTPError on unexpected types and coerce int->str, so they
# delegate to the strict local optional_*_field helpers, not the shared ones.
def first_string_field(payload: dict[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = optional_string_field(payload, key)
        if value:
            return value
    return None


def int_field(payload: dict[str, object], key: str) -> int:
    value = optional_int_field(payload, key)
    return 0 if value is None else value


def optional_int_field(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    msg = f"NCBI response field {key} must be an integer"
    raise HTTPError(msg)


def first_int_field(payload: dict[str, object], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = optional_int_field(payload, key)
        if value is not None:
            return value
    return None


def provenance(endpoint: str) -> dict[str, object]:
    return {
        "provider": "ncbi-entrez",
        "endpoint": endpoint,
        "source_db": PROTEIN_DB,
        "retrieved_at": retrieved_at(),
    }


def print_search_table(result: dict[str, object]) -> None:
    raw_records = result.get("records")
    records = raw_records if isinstance(raw_records, list) else []
    if not records:
        print("No protein records found.")
        return
    rows = []
    for record in records:
        if not isinstance(record, dict):
            continue
        rows.append(
            (
                display(record.get("accession")),
                display(record.get("name") or record.get("title")),
                display(record.get("organism")),
                display(record.get("length")),
                display(record.get("source_database")),
            )
        )
    print(
        markdown_table(
            ("Accession", "Name", "Organism", "Length", "Source"),
            rows,
        )
    )
