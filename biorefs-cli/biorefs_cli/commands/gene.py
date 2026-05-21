"""NCBI Gene workflows."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from biorefs_cli.config import load_config
from biorefs_cli.errors import CLIError, ConfigError
from biorefs_cli.ncbi_client import NCBIClient
from biorefs_cli.output import markdown_table, print_json

if TYPE_CHECKING:
    from biorefs_cli.http import JsonObject, JsonValue

TAXON_ALIASES = {"human": "9606", "mouse": "10090"}
LINK_TARGETS = {
    "pubmed": "pubmed",
    "protein": "protein",
    "nucleotide": "nuccore",
    "clinvar": "clinvar",
}


class GeneClient(Protocol):
    def request_json(
        self, endpoint: str, params: dict[str, str | int]
    ) -> JsonObject: ...


class AmbiguousGeneError(CLIError):
    def __init__(self, symbol: str, candidates: list[dict[str, object]]) -> None:
        super().__init__("ambiguous gene symbol; provide --gene-id")
        self.symbol = symbol
        self.candidates = candidates


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("gene", help="NCBI Gene workflows")
    parser.add_argument("--config", type=Path)
    gene_subcommands = parser.add_subparsers(dest="gene_command", required=True)

    search = gene_subcommands.add_parser("search", help="Search genes")
    search.add_argument("query")
    search.add_argument("--taxon", required=True)
    search.add_argument("--limit", type=positive_int, default=10)
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
    links.add_argument("--gene-id", required=True)
    links.add_argument("--to", required=True, choices=tuple(LINK_TARGETS))
    links.add_argument("--json", action="store_true")
    links.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    try:
        validate_args(args)
        client = client_from_args(args)
        payload = run_gene_command(client, args)
    except AmbiguousGeneError as exc:
        if getattr(args, "json", False):
            print_json(ambiguous_error_payload(exc))
            return exc.exit_code
        raise
    except CLIError as exc:
        if getattr(args, "json", False):
            print_json(error_payload(exc))
            return exc.exit_code
        raise
    if args.json:
        print_json(payload)
    elif args.gene_command == "search":
        print(search_markdown(payload))
    elif args.gene_command == "fetch":
        print(fetch_markdown(payload))
    else:
        print(links_markdown(payload))
    return 0


def validate_args(args: argparse.Namespace) -> None:
    if args.gene_command == "fetch":
        if bool(args.gene_id) == bool(args.symbol):
            msg = "provide exactly one of --gene-id or --symbol"
            raise CLIError(msg, exit_code=2)
        if args.symbol and not args.taxon:
            msg = "--taxon is required with --symbol"
            raise CLIError(msg, exit_code=2)


def client_from_args(args: argparse.Namespace) -> NCBIClient:
    config = load_config(args.config)
    if not config.email:
        msg = "NCBI email missing; run setup --email or set email in config"
        raise ConfigError(msg)
    return NCBIClient.from_config(config)


def run_gene_command(client: GeneClient, args: argparse.Namespace) -> dict[str, object]:
    if args.gene_command == "search":
        return search_genes(client, args.query, taxon=args.taxon, limit=args.limit)
    if args.gene_command == "fetch":
        return fetch_gene(
            client,
            gene_id=args.gene_id,
            symbol=args.symbol,
            taxon=args.taxon,
            links=parse_link_targets(args.links),
        )
    if args.gene_command == "links":
        return link_gene(client, args.gene_id, args.to)
    msg = f"unknown gene command: {args.gene_command}"
    raise CLIError(msg, exit_code=2)


def search_genes(
    client: GeneClient,
    query: str,
    *,
    taxon: str,
    limit: int,
) -> dict[str, object]:
    tax_id = parse_taxon(taxon)
    search = client.request_json(
        "esearch",
        {
            "db": "gene",
            "term": gene_search_term(query, tax_id),
            "retmode": "json",
            "retmax": limit,
            "retstart": 0,
        },
    )
    ids = esearch_ids(search)
    records = summarize_genes(client, ids) if ids else []
    for rank, record in enumerate(records, start=1):
        record["rank"] = rank
    return {
        "query": query,
        "taxon": tax_id,
        "count": esearch_count(search),
        "query_translation": esearch_query_translation(search),
        "records": records,
        "identifiers": {},
        "sources": [source("esearch", "gene"), source("esummary", "gene")],
        "warnings": [],
        "missing": [],
    }


def fetch_gene(
    client: GeneClient,
    *,
    gene_id: str | None,
    symbol: str | None,
    taxon: str | None,
    links: list[str],
) -> dict[str, object]:
    if bool(gene_id) == bool(symbol):
        msg = "provide exactly one of --gene-id or --symbol"
        raise CLIError(msg, exit_code=2)
    resolved_from: dict[str, object] | None = None
    if symbol:
        if not taxon:
            msg = "--taxon is required with --symbol"
            raise CLIError(msg, exit_code=2)
        gene_id, candidates = resolve_symbol(client, symbol, taxon)
        resolved_from = {"symbol": symbol, "candidates": candidates}
    if gene_id is None:
        msg = "gene id could not be resolved"
        raise CLIError(msg)
    records = summarize_genes(client, [gene_id])
    if not records:
        msg = f"NCBI Gene ID not found: {gene_id}"
        raise CLIError(msg)
    record = records[0]
    if resolved_from is not None:
        record["resolved_from"] = resolved_from
    record["links"] = {
        target: link_gene(client, gene_id, target)["links"] for target in links
    }
    return {
        "record": record,
        "identifiers": record.get("identifiers", {}),
        "sources": [source("esummary", "gene")],
        "warnings": [],
        "missing": missing_gene_fields(record),
    }


def link_gene(client: GeneClient, gene_id: str, target: str) -> dict[str, object]:
    target_db = LINK_TARGETS[target]
    raw = client.request_json(
        "elink",
        {
            "dbfrom": "gene",
            "db": target_db,
            "id": gene_id,
            "retmode": "json",
        },
    )
    links = parse_elink(raw, source_db="gene", requested_target_db=target_db)
    return {
        "source_gene_id": gene_id,
        "target": target,
        "links": links,
        "identifiers": {"gene_id": gene_id},
        "sources": [source("elink", target_db)],
        "warnings": [],
        "missing": [],
    }


def resolve_symbol(
    client: GeneClient,
    symbol: str,
    taxon: str,
) -> tuple[str, list[dict[str, object]]]:
    result = search_genes(client, symbol, taxon=taxon, limit=10)
    candidates = object_list(result.get("records"))
    if not candidates:
        msg = f"no NCBI Gene candidate for {symbol!r} in taxon {parse_taxon(taxon)}"
        raise CLIError(msg)
    exact = [
        candidate
        for candidate in candidates
        if str(
            candidate.get("official_symbol") or candidate.get("symbol") or ""
        ).upper()
        == symbol.upper()
    ]
    if len(exact) == 1:
        return candidate_gene_id(exact[0]), candidates
    if len(candidates) == 1 and not exact:
        return candidate_gene_id(candidates[0]), candidates
    raise AmbiguousGeneError(symbol, candidates)


def summarize_genes(client: GeneClient, ids: list[str]) -> list[dict[str, object]]:
    summary = client.request_json(
        "esummary",
        {
            "db": "gene",
            "id": ",".join(ids),
            "retmode": "json",
            "version": "2.0",
        },
    )
    return parse_gene_summaries(summary)


def parse_gene_summaries(data: JsonObject) -> list[dict[str, object]]:
    result = as_object(data.get("result"))
    records: list[dict[str, object]] = []
    for uid in string_list(result.get("uids")):
        doc = as_object(result.get(uid))
        if not doc:
            continue
        records.append(parse_gene_docsum(uid, doc))
    return records


def parse_gene_docsum(uid: str, doc: dict[str, JsonValue]) -> dict[str, object]:
    organism = as_object(doc.get("organism"))
    tax_id = optional_str(organism.get("taxid"))
    official_symbol = first_value(
        optional_str(doc.get("nomenclaturesymbol")),
        optional_str(doc.get("name")),
    )
    description = optional_str(doc.get("description"))
    return {
        "identifiers": {"gene_id": uid, "tax_id": tax_id},
        "gene_id": uid,
        "official_symbol": official_symbol,
        "symbol": optional_str(doc.get("name")) or official_symbol,
        "name": first_value(optional_str(doc.get("nomenclaturename")), description),
        "description": description,
        "organism": {
            "scientific_name": optional_str(organism.get("scientificname")),
            "common_name": optional_str(organism.get("commonname")),
            "tax_id": tax_id,
        },
        "aliases": parse_aliases(doc.get("otheraliases")),
        "map_location": optional_str(doc.get("maplocation")),
        "summary": optional_str(doc.get("summary")),
        "source_urls": [f"https://www.ncbi.nlm.nih.gov/gene/{uid}"],
        "provenance": {"provider": "ncbi", "endpoint": "esummary", "db": "gene"},
        "sources": [source("esummary", "gene")],
        "warnings": [],
        "missing": [],
    }


def parse_elink(
    data: JsonObject,
    *,
    source_db: str,
    requested_target_db: str,
) -> list[dict[str, object]]:
    links: list[dict[str, object]] = []
    for linkset_value in value_list(data.get("linksets")):
        linkset = as_object(linkset_value)
        source_id = first_value(*string_list(linkset.get("ids")))
        for linksetdb_value in value_list(linkset.get("linksetdbs")):
            linksetdb = as_object(linksetdb_value)
            target_db = optional_str(linksetdb.get("dbto")) or requested_target_db
            link_name = optional_str(linksetdb.get("linkname"))
            for link_value in value_list(linksetdb.get("links")):
                target_id, score = parse_link_value(link_value)
                if target_id is None:
                    continue
                links.append(
                    {
                        "source_db": source_db,
                        "source_id": source_id,
                        "target_db": target_db,
                        "target_id": target_id,
                        "link_name": link_name,
                        "score": score,
                        "provider": "ncbi-elink",
                        "identifiers": link_identifiers(target_db, target_id),
                        "sources": [source("elink", target_db)],
                    }
                )
    return links


def parse_link_value(value: JsonValue) -> tuple[str | None, int | None]:
    if isinstance(value, str | int):
        return str(value), None
    item = as_object(value)
    target_id = optional_str(item.get("id"))
    score_value = item.get("score")
    return target_id, score_value if isinstance(score_value, int) else None


def parse_taxon(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in TAXON_ALIASES:
        return TAXON_ALIASES[normalized]
    if normalized.isdecimal():
        return normalized
    msg = "taxon must be human, mouse, or numeric taxonomy ID"
    raise CLIError(msg, exit_code=2)


def parse_link_targets(value: str | None) -> list[str]:
    if not value:
        return []
    targets = [item.strip().lower() for item in value.split(",") if item.strip()]
    invalid = [target for target in targets if target not in LINK_TARGETS]
    if invalid:
        msg = f"unsupported link target(s): {', '.join(invalid)}"
        raise CLIError(msg, exit_code=2)
    return targets


def gene_search_term(query: str, tax_id: str) -> str:
    clean_query = query.strip()
    return f"(({clean_query}[Gene Name]) OR ({clean_query}[All Fields])) AND txid{tax_id}[Organism:exp]"


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        msg = "must be a positive integer"
        raise argparse.ArgumentTypeError(msg) from exc
    if parsed <= 0:
        msg = "must be a positive integer"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def search_markdown(payload: dict[str, object]) -> str:
    return markdown_table(
        ("Rank", "Gene ID", "Symbol", "Organism", "Description", "URL"),
        (
            (
                record.get("rank", ""),
                record.get("gene_id", ""),
                record.get("official_symbol", ""),
                organism_text(record),
                record.get("description", ""),
                first_url(record),
            )
            for record in object_list(payload.get("records"))
        ),
    )


def fetch_markdown(payload: dict[str, object]) -> str:
    record = as_plain_object(payload.get("record"))
    rows: list[tuple[str, object]] = [
        ("Gene ID", record.get("gene_id", "")),
        ("Official symbol", record.get("official_symbol", "")),
        ("Description", record.get("description", "")),
        ("Organism", organism_text(record)),
        ("Map location", record.get("map_location", "")),
        ("Aliases", ", ".join(str(item) for item in plain_list(record.get("aliases")))),
        ("URL", first_url(record)),
        ("Summary", record.get("summary", "")),
    ]
    link_groups = as_plain_object(record.get("links"))
    for target, target_links in link_groups.items():
        rows.append((f"{target} links", len(plain_list(target_links))))
    return markdown_table(("Field", "Value"), rows)


def links_markdown(payload: dict[str, object]) -> str:
    return markdown_table(
        ("Source Gene", "Target DB", "Target ID", "Link name"),
        (
            (
                link.get("source_id", ""),
                link.get("target_db", ""),
                link.get("target_id", ""),
                link.get("link_name", ""),
            )
            for link in object_list(payload.get("links"))
        ),
    )


def ambiguous_error_payload(exc: AmbiguousGeneError) -> dict[str, object]:
    return {
        "error": {"type": "ambiguous-gene", "message": "ambiguous gene symbol"},
        "candidates": [candidate_summary(candidate) for candidate in exc.candidates],
        "identifiers": {},
        "sources": [source("esearch", "gene"), source("esummary", "gene")],
        "warnings": [f"provide --gene-id instead of ambiguous symbol {exc.symbol!r}"],
        "missing": [],
    }


def error_payload(exc: CLIError) -> dict[str, object]:
    return {
        "error": {"type": exc.__class__.__name__, "message": exc.safe_message},
        "identifiers": {},
        "sources": [],
        "warnings": [],
        "missing": ["email"] if isinstance(exc, ConfigError) else [],
    }


def missing_gene_fields(record: dict[str, object]) -> list[str]:
    return [
        field
        for field in ("official_symbol", "description", "organism", "summary")
        if not record.get(field)
    ]


def candidate_gene_id(candidate: dict[str, object]) -> str:
    identifiers = as_plain_object(candidate.get("identifiers"))
    gene_id = identifiers.get("gene_id") or candidate.get("gene_id")
    if gene_id is None:
        msg = "candidate did not include NCBI Gene ID"
        raise CLIError(msg)
    return str(gene_id)


def candidate_summary(candidate: dict[str, object]) -> dict[str, object]:
    organism = as_plain_object(candidate.get("organism"))
    return {
        "gene_id": candidate_gene_id(candidate),
        "official_symbol": candidate.get("official_symbol"),
        "description": candidate.get("description"),
        "organism": organism.get("scientific_name"),
        "tax_id": organism.get("tax_id"),
    }


def link_identifiers(target_db: str, target_id: str) -> dict[str, str]:
    if target_db == "pubmed":
        return {"pmid": target_id}
    if target_db == "protein":
        return {"protein_id": target_id}
    if target_db == "nuccore":
        return {"nucleotide_id": target_id}
    if target_db == "clinvar":
        return {"clinvar_id": target_id}
    return {"uid": target_id}


def source(endpoint: str, db: str) -> dict[str, str]:
    return {"provider": "ncbi", "endpoint": endpoint, "db": db}


def esearch_ids(data: JsonObject) -> list[str]:
    result = as_object(data.get("esearchresult"))
    return string_list(result.get("idlist"))


def esearch_count(data: JsonObject) -> int:
    result = as_object(data.get("esearchresult"))
    count = result.get("count")
    if isinstance(count, int):
        return count
    if isinstance(count, str) and count.isdecimal():
        return int(count)
    return 0


def esearch_query_translation(data: JsonObject) -> str | None:
    result = as_object(data.get("esearchresult"))
    return optional_str(result.get("querytranslation"))


def parse_aliases(value: JsonValue) -> list[str]:
    if not isinstance(value, str) or value in {"", "-"}:
        return []
    return [
        item.strip()
        for item in value.split(",")
        if item.strip() and item.strip() != "-"
    ]


def first_value(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def first_url(record: dict[str, object]) -> str:
    urls = plain_list(record.get("source_urls"))
    return str(urls[0]) if urls else ""


def organism_text(record: dict[str, object]) -> str:
    organism = as_plain_object(record.get("organism"))
    scientific = organism.get("scientific_name")
    tax_id = organism.get("tax_id")
    if scientific and tax_id:
        return f"{scientific} (taxid:{tax_id})"
    return str(scientific or tax_id or "")


def optional_str(value: JsonValue | object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_object(value: JsonValue | object) -> dict[str, JsonValue]:
    if isinstance(value, dict):
        return cast("dict[str, JsonValue]", value)
    return {}


def value_list(value: JsonValue | object) -> list[JsonValue]:
    if isinstance(value, list):
        return cast("list[JsonValue]", value)
    return []


def string_list(value: JsonValue | object) -> list[str]:
    return [str(item) for item in value_list(value)]


def as_plain_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return {}


def object_list(value: object) -> list[dict[str, object]]:
    return [item for item in plain_list(value) if isinstance(item, dict)]


def plain_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []
