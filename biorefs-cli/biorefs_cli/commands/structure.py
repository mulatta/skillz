"""biorefs-cli structure: RCSB PDB and AlphaFold structure retrieval.

Completes the protein workflow: `uniprot fetch` emits PDB ids as cross-reference
pointers, and these subcommands resolve them to ranked search results, metadata,
and coordinate files. Retrieval only — keyless REST against RCSB and the
AlphaFold Database. Structural analysis (alignment, SASA, folding) is out of
scope and would belong to a dedicated structural-biology tool.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from biorefs_cli.config import Config, load_config
from biorefs_cli.errors import CLIError, HTTPError
from biorefs_cli.output import display, markdown_table, print_json
from biorefs_cli.rcsb_graphql import EntryMeta, MetadataBackend, RcsbGraphQLClient

if TYPE_CHECKING:
    import argparse

    from biorefs_cli.http import HttpClient, JsonObject

USER_AGENT = "biorefs-cli/0.1 (https://github.com/mulatta/skillz)"

# --- identifiers -----------------------------------------------------------

PDB_ID_RE = re.compile(r"^[1-9][A-Za-z0-9]{3}$")
EXTENDED_PDB_ID_RE = re.compile(r"^pdb_[0-9a-z]{8}$")
UNIPROT_ACCESSION_RE = re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})"
    r"(?:-[0-9]+)?$"
)


def normalize_pdb_id(value: str) -> str:
    raw = value.strip()
    extended = raw.lower()
    if EXTENDED_PDB_ID_RE.fullmatch(extended):
        return extended
    upper = raw.upper()
    if PDB_ID_RE.fullmatch(upper):
        return upper
    msg = f"invalid PDB id: {value}"
    raise CLIError(msg, exit_code=2)


def normalize_uniprot_accession(value: str) -> str:
    accession = value.strip().upper()
    if not accession or not UNIPROT_ACCESSION_RE.fullmatch(accession):
        msg = f"invalid UniProt accession: {value}"
        raise CLIError(msg, exit_code=2)
    return accession


# --- search ----------------------------------------------------------------

SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
DEFAULT_LIMIT = 25
MAX_LIMIT = 100
UNIPROT_ACCESSION_ATTR = (
    "rcsb_polymer_entity_container_identifiers"
    ".reference_sequence_identifiers.database_accession"
)
RESOLUTION_ATTR = "rcsb_entry_info.resolution_combined"
ORGANISM_ATTR = "rcsb_entity_source_organism.ncbi_taxonomy_id"
METHOD_ATTR = "exptl.method"
METHOD_MAP = {
    "xray": "X-RAY DIFFRACTION",
    "nmr": "SOLUTION NMR",
    "em": "ELECTRON MICROSCOPY",
    "cryoem": "ELECTRON MICROSCOPY",
}
DEFAULT_SEQUENCE_IDENTITY = 0.3
DEFAULT_SEQUENCE_EVALUE = 1.0


class SearchBackend(Protocol):
    def search(self, payload: dict[str, object]) -> JsonObject: ...


class RcsbSearchClient:
    def __init__(self, *, config: Config, http: object | None = None) -> None:
        from biorefs_cli.http import HttpClient

        self.http = cast(
            "HttpClient", http or HttpClient(timeout_seconds=config.timeout_seconds)
        )

    def search(self, payload: dict[str, object]) -> JsonObject:
        return self.http.post_json(
            SEARCH_URL,
            payload,
            headers={"User-Agent": USER_AGENT},
            rate_limit_source="rcsb",
        )


@dataclass(frozen=True, slots=True)
class SearchQuery:
    primary_kind: str
    primary_value: str
    method: str | None
    max_resolution: float | None
    organism: str | None


@dataclass(frozen=True, slots=True)
class Hit:
    pdb_id: str
    score: float | None


class SearchService:
    def __init__(self, backend: SearchBackend, enricher: MetadataBackend) -> None:
        self.backend = backend
        self.enricher = enricher

    def run(self, query: SearchQuery, *, limit: int, offset: int) -> dict[str, object]:
        validate_limit(limit)
        validate_offset(offset)
        payload = build_search_payload(query, limit=limit, offset=offset)
        response = cast("dict[str, object]", self.backend.search(payload))
        total = int_field(response, "total_count")
        hits = parse_hits(response)
        meta = self.enrich([hit.pdb_id for hit in hits])
        warnings = [] if meta is not None else ["metadata enrichment unavailable"]
        records = [build_record(hit, (meta or {}).get(hit.pdb_id)) for hit in hits]
        result: dict[str, object] = {
            "source": "rcsb",
            "query_kind": query.primary_kind,
            "query_value": query.primary_value,
            "total_count": total,
            "offset": offset,
            "returned": len(records),
            "records": records,
            "provenance": search_provenance(),
        }
        if warnings:
            result["warnings"] = warnings
        return result

    def enrich(self, ids: list[str]) -> dict[str, EntryMeta] | None:
        if not ids:
            return {}
        try:
            return self.enricher.entry_metadata(ids)
        except HTTPError:
            return None


def build_record(hit: Hit, meta: EntryMeta | None) -> dict[str, object]:
    record: dict[str, object] = {"pdb_id": hit.pdb_id, "score": hit.score}
    if meta is not None:
        record.update(meta.to_json_dict())
    return record


def build_query_from_args(args: argparse.Namespace) -> SearchQuery:
    sequence = read_sequence(args)
    primaries = [
        ("full_text", args.query.strip() if args.query else None),
        ("sequence", sequence),
        ("uniprot", args.uniprot),
    ]
    chosen = [(kind, value) for kind, value in primaries if value]
    if len(chosen) != 1:
        msg = "provide exactly one of QUERY, --sequence/--sequence-file, or --uniprot"
        raise CLIError(msg, exit_code=2)
    kind, value = chosen[0]
    if kind == "uniprot":
        value = normalize_uniprot_accession(value)
    organism = validate_organism(args.organism)
    return SearchQuery(
        primary_kind=kind,
        primary_value=value,
        method=args.method,
        max_resolution=args.max_resolution,
        organism=organism,
    )


def read_sequence(args: argparse.Namespace) -> str | None:
    if args.sequence:
        return clean_sequence(args.sequence)
    if args.sequence_file:
        try:
            raw = Path(args.sequence_file).read_text(encoding="utf-8")
        except OSError as exc:
            msg = f"could not read sequence file: {args.sequence_file}"
            raise CLIError(msg, exit_code=2) from exc
        return clean_sequence(raw)
    return None


def clean_sequence(raw: str) -> str:
    residues = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.startswith(">")
    ]
    sequence = "".join(residues).upper()
    if not sequence.isalpha():
        msg = "sequence must contain only amino-acid letters"
        raise CLIError(msg, exit_code=2)
    return sequence


def validate_organism(organism: str | None) -> str | None:
    if organism is None:
        return None
    taxon = organism.strip()
    if not taxon.isdecimal():
        msg = "--organism must be an NCBI taxonomy id"
        raise CLIError(msg, exit_code=2)
    return taxon


def build_search_payload(
    query: SearchQuery, *, limit: int, offset: int
) -> dict[str, object]:
    nodes: list[dict[str, object]] = [primary_node(query)]
    nodes.extend(filter_nodes(query))
    combined: dict[str, object] = (
        nodes[0]
        if len(nodes) == 1
        else {"type": "group", "logical_operator": "and", "nodes": nodes}
    )
    return {
        "query": combined,
        "return_type": "entry",
        "request_options": {
            "paginate": {"start": offset, "rows": limit},
            "results_verbosity": "minimal",
        },
    }


def primary_node(query: SearchQuery) -> dict[str, object]:
    if query.primary_kind == "full_text":
        return terminal("full_text", {"value": query.primary_value})
    if query.primary_kind == "sequence":
        return terminal(
            "sequence",
            {
                "sequence_type": "protein",
                "value": query.primary_value,
                "identity_cutoff": DEFAULT_SEQUENCE_IDENTITY,
                "evalue_cutoff": DEFAULT_SEQUENCE_EVALUE,
            },
        )
    return text_attr(UNIPROT_ACCESSION_ATTR, "exact_match", query.primary_value)


def filter_nodes(query: SearchQuery) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []
    if query.method is not None:
        nodes.append(text_attr(METHOD_ATTR, "exact_match", METHOD_MAP[query.method]))
    if query.max_resolution is not None:
        nodes.append(text_attr(RESOLUTION_ATTR, "less_or_equal", query.max_resolution))
    if query.organism is not None:
        nodes.append(text_attr(ORGANISM_ATTR, "exact_match", int(query.organism)))
    return nodes


def terminal(service: str, parameters: dict[str, object]) -> dict[str, object]:
    return {"type": "terminal", "service": service, "parameters": parameters}


def text_attr(attribute: str, operator: str, value: object) -> dict[str, object]:
    return terminal(
        "text", {"attribute": attribute, "operator": operator, "value": value}
    )


def validate_limit(limit: int) -> None:
    if limit < 1:
        msg = "--limit must be at least 1"
        raise CLIError(msg, exit_code=2)
    if limit > MAX_LIMIT:
        msg = f"--limit must be at most {MAX_LIMIT}"
        raise CLIError(msg, exit_code=2)


def validate_offset(offset: int) -> None:
    if offset < 0:
        msg = "--offset must be at least 0"
        raise CLIError(msg, exit_code=2)


def parse_hits(response: dict[str, object]) -> list[Hit]:
    value = response.get("result_set")
    if value is None:
        return []
    if not isinstance(value, list):
        msg = "RCSB response field result_set must be a list"
        raise HTTPError(msg)
    hits: list[Hit] = []
    for item in value:
        if not isinstance(item, dict):
            msg = "RCSB result_set entries must be objects"
            raise HTTPError(msg)
        identifier = item.get("identifier")
        if not isinstance(identifier, str):
            continue
        score = item.get("score")
        hits.append(
            Hit(
                pdb_id=identifier,
                score=float(score)
                if isinstance(score, (int, float)) and not isinstance(score, bool)
                else None,
            )
        )
    return hits


def print_search_table(result: dict[str, object]) -> None:
    raw_records = result.get("records")
    records = raw_records if isinstance(raw_records, list) else []
    total = result.get("total_count")
    if not records:
        print(f"No structures found (total {display(total)}).")
        return
    offset = result.get("offset")
    start = (offset if isinstance(offset, int) else 0) + 1
    rows = []
    for index, record in enumerate(records, start=start):
        if not isinstance(record, dict):
            continue
        orgs = record.get("organisms")
        organism = orgs[0] if isinstance(orgs, list) and orgs else "-"
        rows.append(
            (
                index,
                display(record.get("pdb_id")),
                display(record.get("method")),
                display(record.get("resolution")),
                display(organism),
                display(record.get("title")),
            )
        )
    print(
        markdown_table(
            ("Rank", "PDB ID", "Method", "Resolution", "Organism", "Title"), rows
        )
    )
    print(f"\nShowing {len(records)} of {display(total)} matches.")


# --- fetch -----------------------------------------------------------------

RCSB_FILES_URL = "https://files.rcsb.org/download"
ALPHAFOLD_API_URL = "https://alphafold.ebi.ac.uk/api/prediction"
FORMAT_EXTENSION = {"cif": "cif", "pdb": "pdb"}


@dataclass(frozen=True, slots=True)
class AlphaFoldFile:
    content: bytes
    url: str
    model_id: str


@dataclass(frozen=True, slots=True)
class FetchResult:
    content: bytes
    filename: str
    payload: dict[str, object]


class FetchBackend(Protocol):
    def rcsb_structure(
        self, pdb_id: str, fmt: str, assembly: int | None = None
    ) -> bytes: ...

    def alphafold_structure(self, accession: str, fmt: str) -> AlphaFoldFile: ...


class FetchClient:
    def __init__(self, *, config: Config, http: object | None = None) -> None:
        from biorefs_cli.http import HttpClient

        self.http = cast(
            "HttpClient", http or HttpClient(timeout_seconds=config.timeout_seconds)
        )

    def rcsb_structure(
        self, pdb_id: str, fmt: str, assembly: int | None = None
    ) -> bytes:
        url = rcsb_url(pdb_id, fmt, assembly)
        return self.http.get(
            url, headers={"User-Agent": USER_AGENT}, rate_limit_source="rcsb"
        ).body

    def alphafold_structure(self, accession: str, fmt: str) -> AlphaFoldFile:
        response = self.http.get(
            f"{ALPHAFOLD_API_URL}/{accession}",
            headers={"User-Agent": USER_AGENT},
            rate_limit_source="alphafold",
        )
        prediction = first_prediction(response.body)
        key = "cifUrl" if fmt == "cif" else "pdbUrl"
        url = prediction.get(key)
        if not isinstance(url, str) or not url:
            msg = f"AlphaFold has no {fmt} model for {accession}"
            raise CLIError(msg)
        content = self.http.get(
            url, headers={"User-Agent": USER_AGENT}, rate_limit_source="alphafold"
        ).body
        model_id = url.rstrip("/").split("/")[-1].rsplit(".", 1)[0]
        return AlphaFoldFile(content=content, url=url, model_id=model_id)


class FetchService:
    def __init__(self, backend: FetchBackend) -> None:
        self.backend = backend

    def fetch_rcsb(
        self, pdb_id: str, fmt: str, *, assembly: int | None = None
    ) -> FetchResult:
        normalized = normalize_pdb_id(pdb_id)
        validate_assembly(assembly)
        content = self.backend.rcsb_structure(normalized, fmt, assembly)
        ext = FORMAT_EXTENSION[fmt]
        suffix = f"-assembly{assembly}" if assembly is not None else ""
        payload: dict[str, object] = {
            "source": "rcsb",
            "id": normalized,
            "format": fmt,
            "url": rcsb_url(normalized, fmt, assembly),
            "bytes": len(content),
            "provenance": fetch_provenance("rcsb-files"),
        }
        if assembly is not None:
            payload["assembly"] = assembly
        return FetchResult(
            content=content,
            filename=f"{normalized.lower()}{suffix}.{ext}",
            payload=payload,
        )

    def fetch_alphafold(self, accession: str, fmt: str) -> FetchResult:
        normalized = normalize_uniprot_accession(accession)
        result = self.backend.alphafold_structure(normalized, fmt)
        ext = FORMAT_EXTENSION[fmt]
        return FetchResult(
            content=result.content,
            filename=f"{result.model_id}.{ext}",
            payload={
                "source": "alphafold",
                "id": normalized,
                "model_id": result.model_id,
                "format": fmt,
                "url": result.url,
                "bytes": len(result.content),
                "provenance": fetch_provenance("alphafold-db"),
            },
        )


def write_structure(
    result: FetchResult, *, out_dir: str | None, output: str | None
) -> Path:
    if output is not None:
        path = Path(output)
    else:
        directory = Path(out_dir) if out_dir else Path.cwd()
        path = directory / result.filename
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(result.content)
    except OSError as exc:
        msg = f"could not write structure file: {path}"
        raise CLIError(msg) from exc
    return path


def rcsb_url(pdb_id: str, fmt: str, assembly: int | None = None) -> str:
    ext = FORMAT_EXTENSION[fmt]
    if assembly is not None:
        return f"{RCSB_FILES_URL}/{pdb_id}-assembly{assembly}.{ext}"
    return f"{RCSB_FILES_URL}/{pdb_id}.{ext}"


def validate_assembly(assembly: int | None) -> None:
    if assembly is not None and assembly < 1:
        msg = "--assembly must be at least 1"
        raise CLIError(msg, exit_code=2)


def first_prediction(body: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = "AlphaFold API returned invalid JSON"
        raise HTTPError(msg) from exc
    if not isinstance(decoded, list) or not decoded:
        msg = "AlphaFold API returned no prediction"
        raise HTTPError(msg)
    first = decoded[0]
    if not isinstance(first, dict):
        msg = "AlphaFold API returned an unexpected prediction shape"
        raise HTTPError(msg)
    return cast("dict[str, object]", first)


# --- info ------------------------------------------------------------------

DATA_BASE_URL = "https://data.rcsb.org/rest/v1/core"
INCLUDE_CHOICES = ("entities",)


class DataBackend(Protocol):
    def entry(self, pdb_id: str) -> JsonObject: ...

    def polymer_entity(self, pdb_id: str, entity_id: str) -> JsonObject: ...


class RcsbDataClient:
    def __init__(self, *, config: Config, http: object | None = None) -> None:
        from biorefs_cli.http import HttpClient

        self.http = cast(
            "HttpClient", http or HttpClient(timeout_seconds=config.timeout_seconds)
        )

    def entry(self, pdb_id: str) -> JsonObject:
        return self.http.get_json(
            f"{DATA_BASE_URL}/entry/{pdb_id}",
            headers={"User-Agent": USER_AGENT},
            rate_limit_source="rcsb",
        )

    def polymer_entity(self, pdb_id: str, entity_id: str) -> JsonObject:
        return self.http.get_json(
            f"{DATA_BASE_URL}/polymer_entity/{pdb_id}/{entity_id}",
            headers={"User-Agent": USER_AGENT},
            rate_limit_source="rcsb",
        )


@dataclass(frozen=True, slots=True)
class EntityRecord:
    entity_id: str
    description: str | None
    organism: str | None
    tax_id: int | None
    uniprot: list[str]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "entity_id": self.entity_id,
            "description": self.description,
            "organism": self.organism,
            "tax_id": self.tax_id,
            "uniprot": self.uniprot,
        }


@dataclass(frozen=True, slots=True)
class StructureRecord:
    pdb_id: str
    title: str | None
    method: str | None
    resolution: float | None
    deposit_date: str | None
    ligands: list[str]
    chain_count: int | None
    entity_ids: list[str]
    entities: list[EntityRecord] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source": "rcsb",
            "pdb_id": self.pdb_id,
            "title": self.title,
            "method": self.method,
            "resolution": self.resolution,
            "deposit_date": self.deposit_date,
            "ligands": self.ligands,
            "chain_count": self.chain_count,
            "provenance": info_provenance(),
        }
        if self.entities:
            payload["entities"] = [entity.to_json_dict() for entity in self.entities]
        return payload


class InfoService:
    def __init__(self, backend: DataBackend) -> None:
        self.backend = backend

    def fetch(self, pdb_id: str, *, include: tuple[str, ...]) -> dict[str, object]:
        normalized = normalize_pdb_id(pdb_id)
        entry = cast("dict[str, object]", self.backend.entry(normalized))
        record = parse_entry(normalized, entry)
        if "entities" in include:
            entities = [
                parse_entity(
                    eid,
                    cast(
                        "dict[str, object]",
                        self.backend.polymer_entity(normalized, eid),
                    ),
                )
                for eid in record.entity_ids
            ]
            record = replace_entities(record, entities)
        return record.to_json_dict()


def build_info_result(records: list[dict[str, object]]) -> object:
    if len(records) == 1:
        return records[0]
    return {"source": "rcsb", "records": records}


def parse_include(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    sections = [item.strip() for item in raw.split(",") if item.strip()]
    invalid = [item for item in sections if item not in INCLUDE_CHOICES]
    if invalid:
        msg = f"unknown --include section(s): {', '.join(invalid)}"
        raise CLIError(msg, exit_code=2)
    return tuple(sections)


def parse_entry(pdb_id: str, entry: dict[str, object]) -> StructureRecord:
    struct = object_or_none(entry, "struct")
    info = object_or_none(entry, "rcsb_entry_info") or {}
    accession = object_or_none(entry, "rcsb_accession_info") or {}
    container = object_or_none(entry, "rcsb_entry_container_identifiers") or {}
    return StructureRecord(
        pdb_id=pdb_id,
        title=optional_str(struct, "title") if struct else None,
        method=experimental_method(entry),
        resolution=first_resolution(info),
        deposit_date=date_only(optional_str(accession, "deposit_date")),
        ligands=string_list(info, "nonpolymer_bound_components"),
        chain_count=optional_int(info, "deposited_polymer_entity_instance_count"),
        entity_ids=string_list(container, "polymer_entity_ids"),
    )


def parse_entity(entity_id: str, entity: dict[str, object]) -> EntityRecord:
    core = object_or_none(entity, "rcsb_polymer_entity") or {}
    organisms = object_list(entity, "rcsb_entity_source_organism")
    organism = organisms[0] if organisms else {}
    aligns = object_list(entity, "rcsb_polymer_entity_align")
    uniprot = [
        accession
        for align in aligns
        if optional_str(align, "reference_database_name") == "UniProt"
        and (accession := optional_str(align, "reference_database_accession"))
    ]
    return EntityRecord(
        entity_id=entity_id,
        description=optional_str(core, "pdbx_description"),
        organism=optional_str(organism, "scientific_name"),
        tax_id=optional_int(organism, "ncbi_taxonomy_id"),
        uniprot=uniprot,
    )


def replace_entities(
    record: StructureRecord, entities: list[EntityRecord]
) -> StructureRecord:
    return StructureRecord(
        pdb_id=record.pdb_id,
        title=record.title,
        method=record.method,
        resolution=record.resolution,
        deposit_date=record.deposit_date,
        ligands=record.ligands,
        chain_count=record.chain_count,
        entity_ids=record.entity_ids,
        entities=entities,
    )


def experimental_method(entry: dict[str, object]) -> str | None:
    found = [
        method
        for item in object_list(entry, "exptl")
        if (method := optional_str(item, "method"))
    ]
    return ", ".join(found) if found else None


def first_resolution(info: dict[str, object]) -> float | None:
    value = info.get("resolution_combined")
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, (int, float)) and not isinstance(first, bool):
            return float(first)
    return None


def date_only(value: str | None) -> str | None:
    if value is None:
        return None
    return value.split("T", 1)[0]


def print_info_table(result: dict[str, object]) -> None:
    rows = [
        ("PDB ID", display(result.get("pdb_id"))),
        ("Title", display(result.get("title"))),
        ("Method", display(result.get("method"))),
        ("Resolution", display(result.get("resolution"))),
        ("Deposited", display(result.get("deposit_date"))),
        ("Chains", display(result.get("chain_count"))),
        ("Ligands", ligand_label(result.get("ligands"))),
    ]
    print(markdown_table(("Field", "Value"), rows))
    entities = result.get("entities")
    if isinstance(entities, list) and entities:
        entity_rows = [
            (
                display(entity.get("entity_id")),
                display(entity.get("description")),
                display(entity.get("organism")),
                ", ".join(entity.get("uniprot") or []) or "-",
            )
            for entity in entities
            if isinstance(entity, dict)
        ]
        print()
        print(
            markdown_table(
                ("Entity", "Description", "Organism", "UniProt"), entity_rows
            )
        )


def ligand_label(value: object) -> str:
    if isinstance(value, list) and value:
        return ", ".join(str(item) for item in value)
    return "-"


# --- shared helpers --------------------------------------------------------


def object_or_none(payload: dict[str, object], key: str) -> dict[str, object] | None:
    value = payload.get(key)
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def object_list(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def string_list(payload: dict[str, object], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def int_field(payload: dict[str, object], key: str) -> int:
    value = optional_int(payload, key)
    return 0 if value is None else value


def retrieved_at() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def search_provenance() -> dict[str, object]:
    return {
        "provider": "rcsb-search-api",
        "endpoint": "search",
        "retrieved_at": retrieved_at(),
    }


def fetch_provenance(provider: str) -> dict[str, object]:
    return {"provider": provider, "retrieved_at": retrieved_at()}


def info_provenance() -> dict[str, object]:
    return {
        "provider": "rcsb-data-api",
        "endpoint": "core/entry",
        "retrieved_at": retrieved_at(),
    }


# --- CLI wiring ------------------------------------------------------------


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("structure", help="RCSB/AlphaFold structures")
    structure_subcommands = parser.add_subparsers(
        dest="structure_command", required=True
    )

    search = structure_subcommands.add_parser("search", help="Search RCSB PDB")
    search.add_argument("query", nargs="?", help="full-text query")
    search.add_argument("--sequence", help="protein sequence query")
    search.add_argument("--sequence-file", help="FASTA/raw file with a sequence")
    search.add_argument("--uniprot", help="UniProt accession to find structures for")
    search.add_argument("--method", choices=tuple(METHOD_MAP), help="method filter")
    search.add_argument("--max-resolution", type=float, metavar="ANGSTROM")
    search.add_argument("--organism", metavar="TAXID")
    search.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    search.add_argument("--offset", type=int, default=0, help="pagination start")
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    fetch = structure_subcommands.add_parser("fetch", help="Download a structure file")
    fetch.add_argument("pdb_id", nargs="?", help="PDB id (experimental structure)")
    fetch.add_argument("--uniprot", help="UniProt accession (AlphaFold model)")
    fetch.add_argument("--format", choices=tuple(FORMAT_EXTENSION), default="cif")
    fetch.add_argument(
        "--assembly", type=int, metavar="N", help="biological assembly N"
    )
    fetch.add_argument("--out-dir", metavar="DIR", help="output directory (default: .)")
    fetch.add_argument("--output", metavar="PATH", help="explicit output file path")
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)

    info = structure_subcommands.add_parser("info", help="Show RCSB metadata")
    info.add_argument("pdb_id", nargs="+", help="one or more PDB ids")
    info.add_argument(
        "--include",
        metavar="SECTIONS",
        help=f"comma list of {','.join(INCLUDE_CHOICES)}",
    )
    info.add_argument("--json", action="store_true")
    info.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    config = load_config()
    if args.structure_command == "search":
        return handle_search(args, config)
    if args.structure_command == "fetch":
        return handle_fetch(args, config)
    if args.structure_command == "info":
        return handle_info(args, config)
    msg = "unknown structure subcommand"
    raise CLIError(msg, exit_code=2)


def handle_search(args: argparse.Namespace, config: Config) -> int:
    query = build_query_from_args(args)
    service = SearchService(
        RcsbSearchClient(config=config), RcsbGraphQLClient(config=config)
    )
    limit = DEFAULT_LIMIT if args.limit is None else args.limit
    offset = 0 if args.offset is None else args.offset
    result = service.run(query, limit=limit, offset=offset)
    if args.json:
        print_json(result)
    else:
        print_search_table(result)
    return 0


def handle_fetch(args: argparse.Namespace, config: Config) -> int:
    if bool(args.pdb_id) == bool(args.uniprot):
        msg = "provide exactly one of PDB_ID or --uniprot"
        raise CLIError(msg, exit_code=2)
    if args.assembly is not None and args.uniprot:
        msg = "--assembly applies to PDB ids only, not AlphaFold models"
        raise CLIError(msg, exit_code=2)
    service = FetchService(FetchClient(config=config))
    fmt = args.format or "cif"
    if args.pdb_id:
        result = service.fetch_rcsb(args.pdb_id, fmt, assembly=args.assembly)
    else:
        result = service.fetch_alphafold(args.uniprot, fmt)
    path = write_structure(result, out_dir=args.out_dir, output=args.output)
    payload = {**result.payload, "path": str(path)}
    if args.json:
        print_json(payload)
    else:
        print(path)
    return 0


def handle_info(args: argparse.Namespace, config: Config) -> int:
    include = parse_include(args.include)
    service = InfoService(RcsbDataClient(config=config))
    records = [service.fetch(pdb_id, include=include) for pdb_id in args.pdb_id]
    result = build_info_result(records)
    if args.json:
        print_json(result)
    else:
        for record in records:
            print_info_table(record)
            if record is not records[-1]:
                print()
    return 0
