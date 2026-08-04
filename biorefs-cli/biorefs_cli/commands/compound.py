# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""PubChem compound commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast
from urllib.parse import quote

from biorefs_cli.config import load_config
from biorefs_cli.errors import CLIError, HTTPError, RateLimitError
from biorefs_cli.http import HttpClient, JsonObject
from biorefs_cli.output import markdown_table, print_json

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

PUG_REST_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
PROPERTY_NAMES = (
    "MolecularFormula",
    "MolecularWeight",
    "CanonicalSMILES",
    "IsomericSMILES",
    "InChI",
    "InChIKey",
    "IUPACName",
    "XLogP",
    "TPSA",
    "Charge",
    "Complexity",
)
DEFAULT_INCLUDES = "properties,synonyms,description,safety,classification"
DEFAULT_XREF_TARGETS = "pubmed,gene,protein,patent,pathway"
INCLUDE_CHOICES = {"properties", "synonyms", "description", "safety", "classification"}
XREF_TARGET_CHOICES = {"pubmed", "gene", "protein", "patent", "pathway"}

JsonDict = dict[str, Any]
QueryType = Literal["name", "cid", "smiles", "inchikey", "formula"]
IncludeName = Literal[
    "properties",
    "synonyms",
    "description",
    "safety",
    "classification",
]
XrefTarget = Literal["pubmed", "gene", "protein", "patent", "pathway"]


class JsonGetter(Protocol):
    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> JsonObject: ...


@dataclass(frozen=True, slots=True)
class SourceDetails:
    section: str | None = None
    source_name: str | None = None
    source_record_url: str | None = None


@dataclass(frozen=True, slots=True)
class PugViewContext:
    references: dict[int, JsonDict]
    source_url: str
    identifier: str


class PositiveInteger(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        if not isinstance(values, str):
            parser.error(f"{option_string or self.dest} requires one integer")
        try:
            parsed = int(values)
        except ValueError:
            parser.error(f"{option_string or self.dest} must be an integer")
        if parsed <= 0:
            parser.error(f"{option_string or self.dest} must be positive")
        setattr(namespace, self.dest, parsed)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("compound", help="PubChem compound workflows")
    compound_subcommands = parser.add_subparsers(dest="compound_command", required=True)

    search = compound_subcommands.add_parser("search", help="Search compounds")
    search.add_argument("query")
    search.add_argument(
        "--type",
        choices=("name", "cid", "smiles", "inchikey", "formula"),
        default="name",
    )
    search.add_argument("--limit", action=PositiveInteger, default=10)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    fetch = compound_subcommands.add_parser("fetch", help="Fetch compound record")
    identifier = fetch.add_mutually_exclusive_group(required=True)
    identifier.add_argument("--cid", action=PositiveInteger)
    identifier.add_argument("--name")
    fetch.add_argument("--include", default=DEFAULT_INCLUDES)
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)

    xrefs = compound_subcommands.add_parser(
        "xrefs",
        help="Fetch compound cross-references",
    )
    xrefs.add_argument("--cid", action=PositiveInteger, required=True)
    xrefs.add_argument("--to", default=DEFAULT_XREF_TARGETS)
    xrefs.add_argument("--json", action="store_true")
    xrefs.set_defaults(handler=handle)

    bioactivity = compound_subcommands.add_parser(
        "bioactivity",
        help="Fetch compound bioactivity",
    )
    bioactivity.add_argument("--cid", action=PositiveInteger, required=True)
    bioactivity.add_argument("--target")
    bioactivity.add_argument("--active-only", action="store_true")
    bioactivity.add_argument("--limit", action=PositiveInteger, default=20)
    bioactivity.add_argument("--json", action="store_true")
    bioactivity.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    config = load_config()
    client = CompoundClient(
        HttpClient(timeout_seconds=config.timeout_seconds),
        email=config.email,
    )
    try:
        payload = run_command(args, client)
    except HTTPError as exc:
        payload = error_payload(exc)
        if getattr(args, "json", False):
            print_json(payload)
        else:
            raise
        return exc.exit_code
    if getattr(args, "json", False):
        print_json(payload)
    else:
        print(render_markdown(payload))
    return 0


def run_command(args: argparse.Namespace, client: CompoundClient) -> JsonDict:
    command = cast("str", args.compound_command)
    if command == "search":
        return client.search(
            cast("str", args.query),
            cast("QueryType", args.type),
            limit=cast("int", args.limit),
        )
    if command == "fetch":
        includes = parse_csv_choices(
            cast("str", args.include),
            INCLUDE_CHOICES,
            "include",
        )
        return client.fetch(
            cid=cast("int | None", args.cid),
            name=cast("str | None", args.name),
            include=cast("list[IncludeName]", includes),
        )
    if command == "xrefs":
        targets = parse_csv_choices(cast("str", args.to), XREF_TARGET_CHOICES, "target")
        return client.xrefs(cast("int", args.cid), cast("list[XrefTarget]", targets))
    if command == "bioactivity":
        return client.bioactivity(
            cast("int", args.cid),
            target=cast("str | None", args.target),
            active_only=cast("bool", args.active_only),
            limit=cast("int", args.limit),
        )
    msg = f"unknown compound command: {command}"
    raise CLIError(msg, 2)


def parse_csv_choices(raw: str, choices: set[str], label: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    invalid = sorted(set(values) - choices)
    if invalid:
        msg = f"invalid compound {label}: {', '.join(invalid)}"
        raise CLIError(msg, 2)
    if not values:
        msg = f"empty compound {label}"
        raise CLIError(msg, 2)
    return values


class CompoundClient:
    def __init__(self, http: JsonGetter, *, email: str | None = None) -> None:
        self.http = http
        self.email = email

    def search(self, query: str, query_type: QueryType, *, limit: int) -> JsonDict:
        warnings: list[str] = []
        cids, missing = self.resolve_cids(query, query_type, limit=limit)
        records = self.properties(cids[:limit]) if cids else []
        known_cids = {record.get("cid") for record in records}
        records.extend(minimal_compound(cid) for cid in cids if cid not in known_cids)
        return {
            "type": "compound_search",
            "query": {"type": query_type, "value": query, "limit": limit},
            "identifiers": {"cids": cids[:limit]},
            "records": records[:limit],
            "sources": [source_json("PubChem PUG-REST", PUG_REST_BASE)],
            "warnings": warnings,
            "missing": missing,
        }

    def fetch(
        self,
        *,
        cid: int | None,
        name: str | None,
        include: list[IncludeName],
    ) -> JsonDict:
        missing: list[str] = []
        warnings: list[str] = []
        candidate_cids: list[int] = []
        resolved_cid = cid
        if resolved_cid is None and name is not None:
            candidate_cids, missing = self.resolve_cids(name, "name", limit=10)
            if len(candidate_cids) != 1:
                return self.ambiguous_fetch(name, candidate_cids, missing)
            resolved_cid = candidate_cids[0]
        if resolved_cid is None:
            msg = "compound fetch requires --cid or --name"
            raise CLIError(msg, 2)

        record = minimal_compound(resolved_cid)
        if "properties" in include:
            property_records = self.properties([resolved_cid])
            if property_records:
                record.update(property_records[0])
            else:
                missing.append("properties")
        if "synonyms" in include:
            record["synonyms"] = self.synonyms(resolved_cid)
        pug_sections, pug_missing = self.pug_view_sections(resolved_cid, include)
        record.update(pug_sections)
        missing.extend(pug_missing)
        return {
            "type": "compound_fetch",
            "status": "ok",
            "identifiers": {"cid": resolved_cid, "candidates": candidate_cids},
            "record": record,
            "sources": [source_json("PubChem PUG-REST", PUG_REST_BASE)],
            "warnings": warnings,
            "missing": missing,
        }

    def ambiguous_fetch(
        self,
        name: str,
        candidate_cids: list[int],
        missing: list[str],
    ) -> JsonDict:
        candidates = self.properties(candidate_cids) if candidate_cids else []
        return {
            "type": "compound_fetch",
            "status": "ambiguous" if candidate_cids else "not_found",
            "query": {"name": name},
            "identifiers": {"cids": candidate_cids},
            "candidates": candidates,
            "sources": [source_json("PubChem PUG-REST", PUG_REST_BASE)],
            "warnings": [],
            "missing": missing or (["cid"] if not candidate_cids else []),
        }

    def xrefs(self, cid: int, targets: list[XrefTarget]) -> JsonDict:
        rows: list[JsonDict] = []
        missing: list[str] = []
        for target in targets:
            if target == "pathway":
                pathway_rows = self.pathway_xrefs(cid)
                rows.extend(pathway_rows)
                if not pathway_rows:
                    missing.append("pathway")
                continue
            operation, target_type, id_name, relation = xref_mapping(target)
            url = f"{PUG_REST_BASE}/compound/cid/{cid}/xrefs/{operation}/JSON"
            values = parse_xref_values(self.get_json(url), operation)
            if not values:
                missing.append(target)
            rows.extend(
                {
                    "type": "xref",
                    "subject": {"type": "compound", "cid": cid},
                    "target": {"type": target_type, id_name: str(value)},
                    "relation": relation,
                    "source": "PubChem PUG-REST",
                    "url": public_compound_url(cid),
                    "sources": [source_json("PubChem PUG-REST", url, f"CID:{cid}")],
                }
                for value in values
            )
        return {
            "type": "compound_xrefs",
            "identifiers": {"cid": cid},
            "xrefs": rows,
            "sources": [source_json("PubChem PUG-REST", PUG_REST_BASE)],
            "warnings": [],
            "missing": missing,
        }

    def bioactivity(
        self,
        cid: int,
        *,
        target: str | None,
        active_only: bool,
        limit: int,
    ) -> JsonDict:
        url = f"{PUG_REST_BASE}/compound/cid/{cid}/assaysummary/JSON"
        all_rows = [
            normalize_bioactivity_row(cid, row, url)
            for row in parse_assay_rows(self.get_json(url))
        ]
        filtered_rows = filter_bioactivity_rows(
            all_rows,
            target=target,
            active_only=active_only,
        )
        returned_rows = filtered_rows[:limit]
        return {
            "type": "compound_bioactivity",
            "identifiers": {"cid": cid},
            "rows": returned_rows,
            "counts": {"before_filter": len(all_rows), "returned": len(returned_rows)},
            "sources": [source_json("PubChem PUG-REST", url, f"CID:{cid}")],
            "warnings": [
                "Assay outcomes are assay-specific evidence; mechanism is not inferred.",
            ],
            "missing": [] if returned_rows else ["bioactivity"],
        }

    def resolve_cids(
        self,
        query: str,
        query_type: QueryType,
        *,
        limit: int,
    ) -> tuple[list[int], list[str]]:
        if query_type == "cid":
            try:
                return [int(query)], []
            except ValueError as exc:
                msg = "compound search --type cid requires integer QUERY"
                raise CLIError(msg, 2) from exc
        input_type = "fastformula" if query_type == "formula" else query_type
        url = f"{PUG_REST_BASE}/compound/{input_type}/{quote(query, safe='')}/cids/JSON"
        cids = parse_cids(self.get_json(url))[:limit]
        return cids, [] if cids else ["cids"]

    def properties(self, cids: list[int]) -> list[JsonDict]:
        if not cids:
            return []
        joined_cids = ",".join(str(cid) for cid in cids)
        url = f"{PUG_REST_BASE}/compound/cid/{joined_cids}/property/{','.join(PROPERTY_NAMES)}/JSON"
        return parse_properties(self.get_json(url), url)

    def synonyms(self, cid: int) -> JsonDict:
        url = f"{PUG_REST_BASE}/compound/cid/{cid}/synonyms/JSON"
        values = parse_synonyms(self.get_json(url))
        return {
            "items": values[:20],
            "total": len(values),
            "source": source_json("PubChem PUG-REST", url, f"CID:{cid}"),
        }

    def pug_view_sections(
        self,
        cid: int,
        include: list[IncludeName],
    ) -> tuple[dict[str, list[JsonDict]], list[str]]:
        wanted = [str(item) for item in include if item in PUG_VIEW_INCLUDE_HEADINGS]
        if not wanted:
            return {}, []
        url = f"{PUG_VIEW_BASE}/data/compound/{cid}/JSON"
        sections = extract_pug_view_sections(
            self.get_json(url),
            wanted,
            url,
            f"CID:{cid}",
        )
        missing = [item for item in wanted if not sections.get(item)]
        return sections, missing

    def pathway_xrefs(self, cid: int) -> list[JsonDict]:
        url = f"{PUG_VIEW_BASE}/data/compound/{cid}/JSON"
        sections = extract_pug_view_sections(
            self.get_json(url),
            ["pathway"],
            url,
            f"CID:{cid}",
        )
        return [
            {
                "type": "xref",
                "subject": {"type": "compound", "cid": cid},
                "target": {"type": "pathway", "text": row.get("text", "")},
                "relation": "mentioned_in_pathway_section",
                "source": "PubChem PUG-View",
                "url": public_compound_url(cid),
                "sources": row.get("sources", []),
            }
            for row in sections.get("pathway", [])
        ]

    def get_json(self, url: str) -> JsonObject:
        return self.http.get_json(
            url,
            headers={"User-Agent": user_agent(self.email)},
            rate_limit_source="pubchem",
        )


PUG_VIEW_INCLUDE_HEADINGS = {
    "description": ("record description", "description"),
    "safety": ("safety and hazards", "hazards identification", "ghs classification"),
    "classification": (
        "classification",
        "mesh pharmacological classification",
        "chebi ontology",
    ),
    "pathway": ("biomolecular interactions and pathways", "pathways"),
}


def xref_mapping(target: XrefTarget) -> tuple[str, str, str, str]:
    mappings: dict[XrefTarget, tuple[str, str, str, str]] = {
        "pubmed": ("PubMedID", "pubmed", "pmid", "referenced_in"),
        "gene": ("GeneID", "gene", "gene_id", "has_pubchem_xref"),
        "protein": ("ProteinGI", "protein", "protein_gi", "has_pubchem_xref"),
        "patent": ("PatentID", "patent", "patent_id", "mentioned_in_patent"),
    }
    return mappings[target]


def user_agent(email: str | None) -> str:
    if email:
        return f"biorefs-cli/0.1 ({email})"
    return "biorefs-cli/0.1"


def source_json(
    source: str,
    source_url: str,
    identifier: str | None = None,
    details: SourceDetails | None = None,
) -> JsonDict:
    source_details = details or SourceDetails()
    data: JsonDict = {
        "source": source,
        "source_url": source_url,
        "retrieved_at": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
    }
    optional_values = {
        "identifier": identifier,
        "section": source_details.section,
        "source_name": source_details.source_name,
        "source_record_url": source_details.source_record_url,
    }
    data.update({key: value for key, value in optional_values.items() if value})
    return data


def public_compound_url(cid: int) -> str:
    return f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"


def parse_cids(data: JsonObject) -> list[int]:
    identifier_list = object_or_empty(data.get("IdentifierList"))
    cid_values = list_or_empty(identifier_list.get("CID"))
    cids: list[int] = []
    for value in cid_values:
        if isinstance(value, int):
            cids.append(value)
        elif isinstance(value, str) and value.isdigit():
            cids.append(int(value))
    return cids


def parse_properties(data: JsonObject, source_url: str) -> list[JsonDict]:
    table = object_or_empty(data.get("PropertyTable"))
    records = list_or_empty(table.get("Properties"))
    return [
        normalize_property(cast("JsonDict", record), source_url)
        for record in records
        if isinstance(record, dict)
    ]


def normalize_property(record: JsonDict, source_url: str) -> JsonDict:
    cid = int(record.get("CID", 0))
    normalized: JsonDict = {
        "type": "compound",
        "cid": cid,
        "name": record.get("Title") or record.get("IUPACName") or str(cid),
        "molecular_formula": record.get("MolecularFormula"),
        "molecular_weight": record.get("MolecularWeight"),
        "canonical_smiles": record.get("CanonicalSMILES"),
        "isomeric_smiles": record.get("IsomericSMILES"),
        "inchi": record.get("InChI"),
        "inchikey": record.get("InChIKey"),
        "iupac_name": record.get("IUPACName"),
        "xlogp": record.get("XLogP"),
        "tpsa": record.get("TPSA"),
        "charge": record.get("Charge"),
        "complexity": record.get("Complexity"),
        "provenance": [source_json("PubChem PUG-REST", source_url, f"CID:{cid}")],
    }
    return {key: value for key, value in normalized.items() if value is not None}


def minimal_compound(cid: int) -> JsonDict:
    return {
        "type": "compound",
        "cid": cid,
        "name": str(cid),
        "provenance": [
            source_json("PubChem PUG-REST", public_compound_url(cid), f"CID:{cid}"),
        ],
    }


def parse_synonyms(data: JsonObject) -> list[str]:
    information = list_or_empty(
        object_or_empty(data.get("InformationList")).get("Information"),
    )
    synonyms: list[str] = []
    for item in information:
        if isinstance(item, dict):
            synonyms.extend(str(value) for value in list_or_empty(item.get("Synonym")))
    return synonyms


def parse_xref_values(data: JsonObject, operation: str) -> list[str]:
    information = list_or_empty(
        object_or_empty(data.get("InformationList")).get("Information"),
    )
    values: list[str] = []
    for item in information:
        if not isinstance(item, dict):
            continue
        raw_values = item.get(operation)
        if isinstance(raw_values, list):
            values.extend(str(value) for value in raw_values)
        elif raw_values is not None:
            values.append(str(raw_values))
    return values


def extract_pug_view_sections(
    data: JsonObject,
    requested: list[str],
    source_url: str,
    identifier: str,
) -> dict[str, list[JsonDict]]:
    record = object_or_empty(data.get("Record"))
    sections = list_or_empty(record.get("Section"))
    context = PugViewContext(reference_map(record), source_url, identifier)
    found: dict[str, list[JsonDict]] = {name: [] for name in requested}
    for section in sections:
        if isinstance(section, dict):
            collect_matching_sections(
                cast("JsonDict", section),
                requested,
                found,
                context,
            )
    return found


def collect_matching_sections(
    section: JsonDict,
    requested: list[str],
    found: dict[str, list[JsonDict]],
    context: PugViewContext,
) -> None:
    heading = str(section.get("TOCHeading") or section.get("Name") or "")
    heading_key = heading.casefold()
    for normalized_name in requested:
        candidates = PUG_VIEW_INCLUDE_HEADINGS[normalized_name]
        if heading_matches(heading_key, candidates):
            found[normalized_name].extend(
                extract_section_items(section, heading, context),
            )
    for child in list_or_empty(section.get("Section")):
        if isinstance(child, dict):
            collect_matching_sections(
                cast("JsonDict", child),
                requested,
                found,
                context,
            )


def heading_matches(heading_key: str, candidates: tuple[str, ...]) -> bool:
    return any(
        heading_key == candidate
        if candidate == "classification"
        else candidate in heading_key
        for candidate in candidates
    )


def extract_section_items(
    section: JsonDict,
    heading: str,
    context: PugViewContext,
) -> list[JsonDict]:
    items: list[JsonDict] = []
    for info in list_or_empty(section.get("Information")):
        if not isinstance(info, dict):
            continue
        info_dict = cast("JsonDict", info)
        text_values = value_strings(info_dict.get("Value"))
        if not text_values:
            continue
        source_details = info_source(info_dict, context.references, heading)
        items.extend(
            section_item(heading, info_dict, text, source_details, context)
            for text in text_values
        )
    return items


def section_item(
    heading: str,
    info: JsonDict,
    text: str,
    source_details: SourceDetails,
    context: PugViewContext,
) -> JsonDict:
    return {
        "heading": heading,
        "name": info.get("Name"),
        "text": text,
        "sources": [
            source_json(
                "PubChem PUG-View",
                context.source_url,
                context.identifier,
                source_details,
            ),
        ],
    }


def reference_map(record: JsonDict) -> dict[int, JsonDict]:
    references: dict[int, JsonDict] = {}
    for raw_reference in list_or_empty(record.get("Reference")):
        if not isinstance(raw_reference, dict):
            continue
        reference = cast("JsonDict", raw_reference)
        number = reference.get("ReferenceNumber")
        if isinstance(number, int):
            references[number] = reference
    return references


def info_source(
    info: JsonDict,
    references: dict[int, JsonDict],
    heading: str,
) -> SourceDetails:
    reference_number = info.get("ReferenceNumber")
    reference = (
        references.get(reference_number) if isinstance(reference_number, int) else None
    )
    source_name = optional_str(reference.get("SourceName")) if reference else None
    record_url = optional_str(reference.get("URL")) if reference else None
    return SourceDetails(
        heading,
        source_name or optional_str(info.get("Name")),
        record_url or optional_str(info.get("URL")),
    )


def value_strings(value: object) -> list[str]:
    return dedupe_clean(collect_value_strings(value))


def collect_value_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, int | float):
        return [str(value)]
    if isinstance(value, list):
        return flatten(collect_value_strings(item) for item in value)
    if not isinstance(value, dict):
        return []
    for key in ("StringWithMarkup", "String", "Number", "Table"):
        if key in value:
            return collect_value_strings(value[key])
    return flatten(collect_value_strings(item) for item in value.values())


def parse_assay_rows(data: JsonObject) -> list[JsonDict]:
    summary_rows = parse_assay_summary_rows(data)
    if summary_rows:
        return summary_rows
    table = object_or_empty(data.get("Table"))
    columns = parse_table_columns(table)
    rows: list[JsonDict] = []
    for raw_row in list_or_empty(table.get("Row")):
        if isinstance(raw_row, dict):
            row = row_from_cells(cast("JsonDict", raw_row), columns)
            if row:
                rows.append(row)
    return rows


def parse_assay_summary_rows(data: JsonObject) -> list[JsonDict]:
    summaries = object_or_empty(data.get("AssaySummaries"))
    raw_rows = list_or_empty(summaries.get("AssaySummary"))
    return [cast("JsonDict", row) for row in raw_rows if isinstance(row, dict)]


def parse_table_columns(table: JsonDict) -> list[str]:
    raw_columns = table.get("Columns")
    if isinstance(raw_columns, dict):
        raw_column_list = raw_columns.get("Column")
    else:
        raw_column_list = raw_columns
    return [str(column) for column in list_or_empty(raw_column_list)]


def row_from_cells(raw_row: JsonDict, columns: list[str]) -> JsonDict | None:
    cells = list_or_empty(raw_row.get("Cell"))
    if not cells:
        return None
    return {
        columns[index] if index < len(columns) else f"column_{index + 1}": cell
        for index, cell in enumerate(cells)
    }


def normalize_bioactivity_row(cid: int, row: JsonDict, source_url: str) -> JsonDict:
    normalized_keys = {normalize_key(key): value for key, value in row.items()}
    aid = text_value(first_present(normalized_keys, ("aid",)))
    outcome = text_value(
        first_present(normalized_keys, ("activity_outcome", "outcome", "activity")),
    ).casefold()
    target = {
        "name": text_value(
            first_present(
                normalized_keys,
                ("target_name", "target", "protein_name", "gene_symbol"),
            ),
        ),
        "gene_id": text_value(first_present(normalized_keys, ("geneid", "gene_id"))),
        "protein_accession": text_value(
            first_present(
                normalized_keys,
                ("protein_accession", "accession", "protein_gi"),
            ),
        ),
    }
    return {
        "type": "bioactivity",
        "cid": cid,
        "aid": aid,
        "outcome": outcome,
        "activity_name": text_value(
            first_present(
                normalized_keys,
                ("activity_name", "activity_type", "readout"),
            ),
        ),
        "activity_value": first_present(
            normalized_keys,
            ("activity_value", "ac50", "ic50", "ec50", "ki", "kd"),
        ),
        "activity_unit": text_value(
            first_present(normalized_keys, ("activity_unit", "unit")),
        ),
        "target": target,
        "assay_source": text_value(
            first_present(normalized_keys, ("source_name", "source")),
        )
        or "PubChem BioAssay",
        "original": row,
        "provenance": [source_json("PubChem PUG-REST", source_url, f"CID:{cid}")],
    }


def filter_bioactivity_rows(
    rows: list[JsonDict],
    *,
    target: str | None,
    active_only: bool,
) -> list[JsonDict]:
    filtered = rows
    if active_only:
        filtered = [row for row in filtered if row.get("outcome") == "active"]
    if target:
        target_lower = target.casefold()
        filtered = [row for row in filtered if target_lower in row_text(row).casefold()]
    return filtered


def row_text(row: JsonDict) -> str:
    parts: list[str] = []
    for value in row.values():
        if isinstance(value, dict):
            parts.extend(str(item) for item in value.values())
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return " ".join(parts)


def first_present(mapping: dict[str, object], keys: tuple[str, ...]) -> object:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def normalize_key(value: str) -> str:
    return "_".join(value.strip().casefold().replace("-", " ").split())


def render_markdown(payload: JsonDict) -> str:
    payload_type = payload.get("type")
    if payload_type == "compound_search":
        return render_compound_table(cast("list[JsonDict]", payload.get("records", [])))
    if payload_type == "compound_fetch":
        return render_fetch(payload)
    if payload_type == "compound_xrefs":
        return render_xref_table(cast("list[JsonDict]", payload.get("xrefs", [])))
    if payload_type == "compound_bioactivity":
        return render_bioactivity_table(cast("list[JsonDict]", payload.get("rows", [])))
    return markdown_table(["Field", "Value"], payload.items())


def render_fetch(payload: JsonDict) -> str:
    status = payload.get("status")
    if status in {"ambiguous", "not_found"}:
        candidates = cast("list[JsonDict]", payload.get("candidates", []))
        if not candidates:
            return "No compound candidates found."
        return "Name is ambiguous.\n\n" + render_compound_table(candidates)
    record = cast("JsonDict", payload.get("record", {}))
    parts = [render_compound_table([record])]
    synonyms = record.get("synonyms")
    if isinstance(synonyms, dict):
        items = list_or_empty(synonyms.get("items"))
        if items:
            parts.append("Synonyms: " + ", ".join(str(item) for item in items[:10]))
    for section_name in ("description", "safety", "classification"):
        parts.extend(render_section(section_name, record.get(section_name)))
    return "\n\n".join(parts)


def render_section(section_name: str, section: object) -> list[str]:
    if not isinstance(section, list) or not section:
        return []
    rows = [
        (str(item.get("heading", section_name)), str(item.get("text", "")))
        for item in section
        if isinstance(item, dict)
    ]
    return [markdown_table(["Section", "Text"], rows)] if rows else []


def render_compound_table(records: list[JsonDict]) -> str:
    return markdown_table(
        ["CID", "Name", "Formula", "Weight", "Canonical SMILES", "InChIKey"],
        (
            (
                record.get("cid", ""),
                record.get("name", ""),
                record.get("molecular_formula", ""),
                record.get("molecular_weight", ""),
                record.get("canonical_smiles", ""),
                record.get("inchikey", ""),
            )
            for record in records
        ),
    )


def render_xref_table(rows: list[JsonDict]) -> str:
    return markdown_table(
        ["Relation", "Target", "URL"],
        (
            (row.get("relation", ""), row.get("target", ""), row.get("url", ""))
            for row in rows
        ),
    )


def render_bioactivity_table(rows: list[JsonDict]) -> str:
    return markdown_table(
        ["AID", "Outcome", "Activity", "Value", "Unit", "Target"],
        (bioactivity_markdown_row(row) for row in rows),
    )


def bioactivity_markdown_row(
    row: JsonDict,
) -> tuple[object, object, object, object, object, object]:
    target = row.get("target")
    target_name = target.get("name", "") if isinstance(target, dict) else ""
    return (
        row.get("aid", ""),
        row.get("outcome", ""),
        row.get("activity_name", ""),
        row.get("activity_value", ""),
        row.get("activity_unit", ""),
        target_name,
    )


def error_payload(exc: HTTPError) -> JsonDict:
    reason = (
        "pubchem-rate-limited" if isinstance(exc, RateLimitError) else "pubchem-network"
    )
    return {
        "status": "unavailable",
        "reason": reason,
        "tried": ["pubchem"],
        "partial": False,
        "warnings": [exc.safe_message],
        "missing": [],
    }


def object_or_empty(value: object) -> JsonDict:
    return cast("JsonDict", value) if isinstance(value, dict) else {}


def list_or_empty(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def text_value(value: object) -> str:
    return "" if value is None else str(value)


def flatten(values: Iterable[list[str]]) -> list[str]:
    return [item for group in values for item in group]


def dedupe_clean(values: list[str]) -> list[str]:
    clean_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = " ".join(value.split())
        if clean and clean not in seen:
            seen.add(clean)
            clean_values.append(clean)
    return clean_values
