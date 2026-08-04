# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""PubChem BioAssay commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

from biorefs_cli.config import Config, load_config
from biorefs_cli.errors import CLIError, HTTPError, RateLimitError
from biorefs_cli.http import HttpClient, JsonObject, JsonValue
from biorefs_cli.output import markdown_heading, markdown_table, print_json

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

PUG_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_ASSAY_URL = "https://pubchem.ncbi.nlm.nih.gov/bioassay/"
PUBCHEM_COMPOUND_URL = "https://pubchem.ncbi.nlm.nih.gov/compound/"
DEFAULT_SEARCH_LIMIT = 20
ACTIVITY_ROW_LIMIT = 25
FETCH_INCLUDE_DEFAULT = ("description", "targets", "concise")
FETCH_INCLUDE_CHOICES = ("description", "targets", "concise", "activity")
TARGET_MISS_STATUSES = {400, 404}
OUTCOME_MAP = {
    1: "inactive",
    2: "active",
    3: "inconclusive",
    4: "unspecified",
    5: "probe",
}
ACTIVITY_NAME_HINTS = ("ic50", "ec50", "ac50", "ki", "kd", "potency", "inhibition")


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("assay", help="PubChem BioAssay workflows")
    assay_subcommands = parser.add_subparsers(dest="assay_command", required=True)
    search = assay_subcommands.add_parser("search", help="Search assays")
    search.add_argument("--target")
    search.add_argument("--compound")
    search.add_argument("--limit", type=positive_int, default=DEFAULT_SEARCH_LIMIT)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)
    fetch = assay_subcommands.add_parser("fetch", help="Fetch assay record")
    fetch.add_argument("--aid", type=positive_int, required=True)
    fetch.add_argument("--include", type=parse_include, default=FETCH_INCLUDE_DEFAULT)
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    config = load_config()
    client = PubChemAssayClient.from_config(config)
    try:
        if args.assay_command == "search":
            return handle_search(args, client)
        if args.assay_command == "fetch":
            return handle_fetch(args, client)
    except HTTPError as exc:
        return handle_http_error(exc, json_output=bool(args.json))
    msg = f"unsupported assay subcommand: {args.assay_command}"
    raise CLIError(msg, 2)


def handle_search(args: argparse.Namespace, client: PubChemAssayClient) -> int:
    if not args.target and not args.compound:
        msg = "assay search requires --target and/or --compound"
        raise CLIError(msg, 2)
    result = client.search_assays(
        target=args.target,
        compound=args.compound,
        limit=args.limit,
    )
    if args.json:
        print_json(result)
    else:
        print(render_search(result))
    return 0


def handle_fetch(args: argparse.Namespace, client: PubChemAssayClient) -> int:
    result = client.fetch_assay(aid=args.aid, include=args.include)
    if args.json:
        print_json(result)
    else:
        print(render_fetch(result))
    return 0


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


def parse_include(value: str) -> tuple[str, ...]:
    sections = tuple(part.strip() for part in value.split(",") if part.strip())
    if not sections:
        msg = "include list cannot be empty"
        raise argparse.ArgumentTypeError(msg)
    invalid = [section for section in sections if section not in FETCH_INCLUDE_CHOICES]
    if invalid:
        msg = f"unknown include section(s): {', '.join(invalid)}"
        raise argparse.ArgumentTypeError(msg)
    return sections


def handle_http_error(exc: HTTPError, *, json_output: bool) -> int:
    if json_output:
        reason = (
            "pubchem-rate-limited"
            if isinstance(exc, RateLimitError)
            else "pubchem-http-error"
        )
        payload: JsonObject = {
            "status": "unavailable",
            "reason": reason,
            "message": exc.safe_message,
            "identifiers": {},
            "sources": [],
            "warnings": [],
            "missing": [],
            "truncated": {},
            "partial": False,
        }
        if exc.status is not None:
            payload["http_status"] = exc.status
        if isinstance(exc, RateLimitError) and exc.retry_after_seconds is not None:
            payload["retry_after_seconds"] = exc.retry_after_seconds
        print_json(payload)
        return 1
    raise exc


@dataclass(frozen=True, slots=True)
class PubChemAssayClient:
    http: HttpClient
    email: str | None = None

    @classmethod
    def from_config(cls, config: Config) -> PubChemAssayClient:
        return cls(
            http=HttpClient(timeout_seconds=config.timeout_seconds),
            email=config.email,
        )

    def search_assays(
        self,
        *,
        target: str | None,
        compound: str | None,
        limit: int,
    ) -> JsonObject:
        retrieved_at = retrieved_timestamp()
        identifiers: JsonObject = {}
        warnings: list[JsonValue] = []
        missing: list[JsonValue] = []
        compound_results: list[JsonObject] | None = None
        target_results: list[JsonObject] | None = None
        target_aids: set[int] | None = None

        if compound:
            cid = self.resolve_cid(compound)
            identifiers["compound"] = {"query": compound, "cid": cid}
            compound_results = self.compound_assay_summary(cid, retrieved_at)

        if target:
            identifiers["target"] = {"query": target}
            target_aids = self.target_aids(target, limit=limit)
            if target_aids:
                target_results = [
                    self.fetch_assay_summary(aid, retrieved_at)
                    for aid in sorted(target_aids)[:limit]
                ]
            else:
                missing.append({"section": "target", "query": target})

        results = merge_search_results(
            compound_results=compound_results,
            target_results=target_results,
            target_aids=target_aids,
            target=target,
        )
        truncated = len(results) > limit
        limited = results[:limit]
        return {
            "type": "assay_search",
            "query": {"target": target, "compound": compound, "limit": limit},
            "identifiers": identifiers,
            "results": cast("JsonValue", limited),
            "sources": cast("JsonValue", sources_for_assays(limited, retrieved_at)),
            "warnings": warnings,
            "missing": missing,
            "truncated": {"results": truncated},
        }

    def fetch_assay(self, *, aid: int, include: Sequence[str]) -> JsonObject:
        retrieved_at = retrieved_timestamp()
        warnings: list[JsonValue] = []
        missing: list[JsonValue] = []
        truncated: JsonObject = {"activity": False}
        result: JsonObject = {
            "type": "assay",
            "aid": aid,
            "identifiers": {"aid": aid},
            "sources": [assay_source(aid, retrieved_at)],
            "warnings": warnings,
            "missing": missing,
            "truncated": truncated,
        }
        description_sections = {"description", "targets", "concise"}
        parsed_description: JsonObject | None = None
        if description_sections.intersection(include):
            parsed_description = parse_assay_description(
                self.assay_description(aid),
                retrieved_at,
            )
            copy_keys(
                result,
                parsed_description,
                ("name", "assay_type", "source_name", "source_ids", "pubmed_refs"),
            )
        if "description" in include:
            if parsed_description is None or not parsed_description.get("description"):
                missing.append({"section": "description"})
            else:
                result["description"] = parsed_description["description"]
        if "targets" in include:
            targets = (
                []
                if parsed_description is None
                else parsed_description.get("targets", [])
            )
            result["targets"] = targets
            if not targets:
                missing.append({"section": "targets"})
        if "concise" in include:
            if parsed_description is None:
                missing.append({"section": "concise"})
            else:
                result["concise"] = concise_metadata(parsed_description)
        if "activity" in include:
            activity = parse_concise_activity(
                self.assay_concise(aid),
                limit=ACTIVITY_ROW_LIMIT,
            )
            result["activity"] = activity["rows"]
            result["activity_summary"] = activity["summary"]
            truncated["activity"] = bool(activity["truncated"])
        return result

    def resolve_cid(self, compound: str) -> int:
        if compound.isdecimal():
            return int(compound)
        payload = self.get_json(f"/compound/name/{quote(compound, safe='')}/cids/JSON")
        cids = int_values(get_path(payload, ("IdentifierList", "CID")))
        if not cids:
            msg = f"PubChem CID not found for compound: {compound}"
            raise CLIError(msg, 1)
        return cids[0]

    def compound_assay_summary(self, cid: int, retrieved_at: str) -> list[JsonObject]:
        payload = self.get_json(f"/compound/cid/{cid}/assaysummary/JSON")
        rows = object_list(get_path(payload, ("AssaySummaries", "AssaySummary")))
        parsed = [parse_assay_summary(row, retrieved_at, cid=cid) for row in rows]
        return [row for row in parsed if row]

    def target_aids(self, target: str, *, limit: int) -> set[int]:
        aids: set[int] = set()
        for path in target_lookup_paths(target):
            try:
                payload = self.get_json(path)
            except HTTPError as exc:
                if exc.status in TARGET_MISS_STATUSES:
                    continue
                raise
            aids.update(extract_aids(payload))
            if len(aids) >= limit:
                return set(sorted(aids)[:limit])
        return aids

    def fetch_assay_summary(self, aid: int, retrieved_at: str) -> JsonObject:
        return parse_assay_description(self.assay_description(aid), retrieved_at)

    def assay_description(self, aid: int) -> JsonObject:
        return self.get_json(f"/assay/aid/{aid}/description/JSON")

    def assay_concise(self, aid: int) -> JsonObject:
        return self.get_json(f"/assay/aid/{aid}/concise/JSON")

    def get_json(self, path: str) -> JsonObject:
        return self.http.get_json(
            f"{PUG_REST}{path}",
            headers={"User-Agent": self.user_agent()},
            rate_limit_source="pubchem",
        )

    def user_agent(self) -> str:
        if self.email:
            return f"biorefs-cli/0.1 ({self.email})"
        return "biorefs-cli/0.1"


def target_lookup_paths(target: str) -> tuple[str, ...]:
    encoded = quote(target, safe="")
    if target.isdecimal():
        return (
            f"/assay/target/geneid/{encoded}/aids/JSON",
            f"/assay/target/gi/{encoded}/aids/JSON",
        )
    return (
        f"/assay/target/genesymbol/{encoded}/aids/JSON",
        f"/assay/target/proteinname/{encoded}/aids/JSON",
    )


def parse_assay_summary(
    row: JsonObject,
    retrieved_at: str,
    *,
    cid: int | None,
) -> JsonObject:
    aid = first_int(row, "AID", "aid")
    if aid is None:
        return {}
    record: JsonObject = {
        "aid": aid,
        "name": first_str(row, "Name", "name", "Title", "AssayName") or "",
        "assay_type": first_str(row, "AssayType", "assay_type") or "",
        "activity_outcome": first_str(row, "ActivityOutcome", "activity_outcome") or "",
        "activity_summary": flat_activity_summary(row),
        "target_hints": cast("JsonValue", target_hints(row)),
        "source": first_str(row, "SourceName", "source_name") or "PubChem BioAssay",
        "source_ids": cast("JsonValue", flat_source_ids(row)),
        "provenance": [assay_source(aid, retrieved_at)],
    }
    if cid is not None:
        record["compound"] = {"cid": cid, "source_url": f"{PUBCHEM_COMPOUND_URL}{cid}"}
    return record


def parse_assay_description(payload: JsonObject, retrieved_at: str) -> JsonObject:
    descr = assay_description_object(payload)
    aid = assay_id(descr)
    source_name = assay_source_name(descr)
    record: JsonObject = {
        "aid": aid,
        "name": first_str(descr, "name", "Name") or "",
        "description": assay_description_text(descr),
        "assay_type": assay_type(descr),
        "source_name": source_name,
        "targets": cast("JsonValue", parse_targets(descr.get("target"))),
        "source_ids": cast("JsonValue", assay_source_ids(descr)),
        "pubmed_refs": cast("JsonValue", parse_pubmed_refs(descr.get("xref"))),
        "source": source_name or "PubChem BioAssay",
        "provenance": [assay_source(aid, retrieved_at)] if aid else [],
    }
    return record


def parse_targets(value: JsonValue | None) -> list[JsonObject]:
    targets: list[JsonObject] = []
    for item in object_list(value):
        xrefs = target_xrefs(item)
        target: JsonObject = {
            "name": first_str(item, "name", "Name", "descr") or "",
            "gene_id": xrefs.get("gene_id", ""),
            "protein_accession": first_str(item, "protein_accession", "accession")
            or xrefs.get("protein_accession", ""),
            "protein_gi": first_str(item, "mol_id", "gi")
            or xrefs.get("protein_gi", ""),
            "organism": target_organism(item),
            "source_ids": xrefs.get("source_ids", []),
        }
        targets.append(target)
    return targets


def target_xrefs(item: JsonObject) -> JsonObject:
    result: JsonObject = {"source_ids": []}
    source_ids: list[JsonValue] = []
    for wrapper in object_list(item.get("xref")):
        xref = object_value(wrapper.get("xref")) or wrapper
        gene_id = first_str(xref, "gene", "GeneID", "gene_id")
        if gene_id:
            result["gene_id"] = gene_id
        protein_gi = first_str(xref, "protein_gi", "gi")
        if protein_gi:
            result["protein_gi"] = protein_gi
        protein_accession = first_str(xref, "protein_accession", "accession")
        if protein_accession:
            result["protein_accession"] = protein_accession
        source_ids.extend(source_id_entries(xref))
    result["source_ids"] = source_ids
    return result


def parse_pubmed_refs(value: JsonValue | None) -> list[JsonObject]:
    refs: list[JsonObject] = []
    for wrapper in object_list(value):
        xref = object_value(wrapper.get("xref")) or wrapper
        pmid = first_str(xref, "pmid", "PMID", "PubMedID")
        if pmid:
            refs.append({"pmid": pmid, "source": "PubChem BioAssay"})
    return refs


def parse_concise_activity(payload: JsonObject, *, limit: int) -> JsonObject:
    root = concise_root(payload)
    definitions = result_definitions(root)
    rows = [
        parse_activity_row(row, definitions) for row in object_list(root.get("data"))
    ]
    returned = rows[:limit]
    return {
        "rows": cast("JsonValue", returned),
        "summary": {
            "total_rows": len(rows),
            "returned_rows": len(returned),
            "outcomes": outcome_counts(rows),
        },
        "truncated": len(rows) > limit,
    }


def parse_activity_row(
    row: JsonObject,
    definitions: dict[int, JsonObject],
) -> JsonObject:
    values = activity_values(row.get("data"), definitions)
    selected = select_activity_value(values)
    outcome = normalize_outcome(row.get("outcome")) or outcome_from_values(values)
    return {
        "sid": first_int(row, "sid", "SID") or 0,
        "cid": first_int(row, "cid", "CID") or 0,
        "outcome": outcome,
        "activity_name": selected.get("name", ""),
        "activity_value": selected.get("value", ""),
        "activity_unit": selected.get("unit", ""),
        "values": cast("JsonValue", values),
        "evidence_note": "Assay-specific activity row; no mechanism inferred.",
    }


def activity_values(
    value: JsonValue | None,
    definitions: dict[int, JsonObject],
) -> list[JsonObject]:
    values: list[JsonObject] = []
    for item in object_list(value):
        tid = first_int(item, "tid", "TID")
        definition = definitions.get(tid or -1, {})
        raw_value = object_value(item.get("value")) or item
        values.append(
            {
                "tid": tid or 0,
                "name": first_str(definition, "name", "Name") or f"TID {tid}",
                "type": first_str(definition, "type", "Type") or "",
                "unit": first_str(definition, "unit", "Unit") or "",
                "value": pubchem_scalar(raw_value),
                "original": raw_value,
            },
        )
    return values


def result_definitions(root: JsonObject) -> dict[int, JsonObject]:
    assay = object_value(root.get("assay")) or root
    descr = object_value(assay.get("descr")) or assay
    definitions: dict[int, JsonObject] = {}
    for key in ("results", "data"):
        for item in object_list(descr.get(key)):
            tid = first_int(item, "tid", "TID")
            if tid is not None:
                definitions[tid] = item
    return definitions


def select_activity_value(values: list[JsonObject]) -> JsonObject:
    for value in values:
        name = str(value.get("name", "")).lower()
        if any(hint in name for hint in ACTIVITY_NAME_HINTS):
            return value
    for value in values:
        scalar = value.get("value")
        if isinstance(scalar, int | float):
            return value
    return values[0] if values else {}


def merge_search_results(
    *,
    compound_results: list[JsonObject] | None,
    target_results: list[JsonObject] | None,
    target_aids: set[int] | None,
    target: str | None,
) -> list[JsonObject]:
    if compound_results is None:
        return target_results or []
    if target_aids:
        return [row for row in compound_results if first_int(row, "aid") in target_aids]
    if target:
        needle = target.lower()
        return [row for row in compound_results if target_matches(row, needle)]
    return compound_results


def target_matches(row: JsonObject, needle: str) -> bool:
    return any(
        needle in str(hint).lower() for hint in object_list(row.get("target_hints"))
    )


def render_search(result: JsonObject) -> str:
    rows: list[tuple[object, ...]] = []
    raw_results = result.get("results")
    if isinstance(raw_results, list):
        for item in raw_results:
            if isinstance(item, dict):
                row = item
                rows.append(
                    (
                        row.get("aid", ""),
                        row.get("name", ""),
                        row.get("assay_type", ""),
                        row.get("activity_outcome", ""),
                        target_hint_text(row.get("target_hints")),
                        row.get("source", ""),
                    ),
                )
    if not rows:
        rows = [("-", "No assays found", "-", "-", "-", "-")]
    return "\n\n".join(
        (
            markdown_heading("PubChem BioAssay search"),
            markdown_table(
                ("AID", "Name", "Assay type", "Activity outcome", "Targets", "Source"),
                rows,
            ),
        ),
    )


def render_fetch(result: JsonObject) -> str:
    aid = result.get("aid", "")
    lines = [markdown_heading(f"PubChem BioAssay AID {aid}")]
    name = result.get("name")
    if name:
        lines.extend(["", f"**Name:** {name}"])
    description = result.get("description")
    if isinstance(description, str) and description:
        lines.extend(["", markdown_heading("Description", level=2), "", description])
    lines.extend(render_targets_section(result))
    lines.extend(render_concise_section(result))
    lines.extend(render_activity_section(result))
    return "\n".join(lines)


def render_targets_section(result: JsonObject) -> list[str]:
    targets = result.get("targets")
    if not isinstance(targets, list) or not targets:
        return []
    rows = []
    for item in targets:
        if isinstance(item, dict):
            target = item
            rows.append(
                (
                    target.get("name", ""),
                    target.get("gene_id", ""),
                    target.get("protein_accession") or target.get("protein_gi", ""),
                    target.get("organism", ""),
                ),
            )
    return [
        "",
        markdown_heading("Targets", level=2),
        "",
        markdown_table(("Name", "Gene ID", "Protein", "Organism"), rows),
    ]


def render_concise_section(result: JsonObject) -> list[str]:
    concise = result.get("concise")
    if not isinstance(concise, dict):
        return []
    rows = [(key, value) for key, value in concise.items() if value]
    return [
        "",
        markdown_heading("Concise metadata", level=2),
        "",
        markdown_table(("Field", "Value"), rows),
    ]


def render_activity_section(result: JsonObject) -> list[str]:
    activity = result.get("activity")
    if not isinstance(activity, list):
        return []
    rows = []
    for item in activity:
        if isinstance(item, dict):
            row = item
            rows.append(
                (
                    row.get("sid", ""),
                    row.get("cid", ""),
                    row.get("outcome", ""),
                    row.get("activity_name", ""),
                    row.get("activity_value", ""),
                    row.get("activity_unit", ""),
                ),
            )
    lines = [
        "",
        markdown_heading("Activity", level=2),
        "",
        markdown_table(("SID", "CID", "Outcome", "Activity", "Value", "Unit"), rows),
    ]
    summary = result.get("activity_summary")
    if isinstance(summary, dict):
        lines.extend(
            [
                "",
                f"Returned {summary.get('returned_rows', 0)} of {summary.get('total_rows', 0)} activity rows.",
            ],
        )
    return lines


def assay_description_object(payload: JsonObject) -> JsonObject:
    containers = object_list(payload.get("PC_AssayContainer"))
    if containers:
        assay = object_value(containers[0].get("assay")) or containers[0]
        return object_value(assay.get("descr")) or assay
    submit = object_value(payload.get("PC_AssaySubmit"))
    if submit:
        assay = object_value(submit.get("assay")) or submit
        return object_value(assay.get("descr")) or assay
    return payload


def concise_root(payload: JsonObject) -> JsonObject:
    submit = object_value(payload.get("PC_AssaySubmit"))
    if submit:
        return submit
    containers = object_list(payload.get("PC_AssayContainer"))
    if containers:
        return containers[0]
    return payload


def assay_id(descr: JsonObject) -> int:
    aid_obj = object_value(descr.get("aid"))
    if aid_obj:
        found = first_int(aid_obj, "id", "aid", "AID")
        if found is not None:
            return found
    return first_int(descr, "aid", "AID") or 0


def assay_description_text(descr: JsonObject) -> str:
    for key in ("description", "protocol", "comment"):
        text = text_value(descr.get(key))
        if text:
            return text
    return ""


def assay_type(descr: JsonObject) -> str:
    return first_str(descr, "assay_type", "activity_outcome_method") or ""


def assay_source_name(descr: JsonObject) -> str:
    source = object_value(descr.get("aid_source"))
    if source:
        db = object_value(source.get("db"))
        if db:
            return first_str(db, "name") or ""
    return first_str(descr, "source_name", "SourceName") or ""


def assay_source_ids(descr: JsonObject) -> list[JsonObject]:
    source = object_value(descr.get("aid_source"))
    if not source:
        return []
    db = object_value(source.get("db"))
    if not db:
        return []
    source_id = object_value(db.get("source_id"))
    value = "" if source_id is None else first_str(source_id, "str", "id")
    if not value:
        return []
    return [{"source": first_str(db, "name") or "", "id": value}]


def flat_source_ids(row: JsonObject) -> list[JsonObject]:
    source_id = first_str(row, "SourceID", "source_id")
    if not source_id:
        return []
    return [{"source": first_str(row, "SourceName") or "", "id": source_id}]


def flat_activity_summary(row: JsonObject) -> JsonObject:
    keys = (
        "ActivityOutcome",
        "ActivityOutcomeMethod",
        "ActivitySummary",
        "ActiveCount",
        "InactiveCount",
        "TestedSIDCount",
    )
    return {to_snake(key): value for key in keys if (value := row.get(key)) is not None}


def target_hints(row: JsonObject) -> list[JsonObject]:
    target: JsonObject = {}
    for source_key, output_key in (
        ("TargetGeneID", "gene_id"),
        ("TargetGeneSymbol", "gene_symbol"),
        ("TargetGI", "protein_gi"),
        ("TargetName", "name"),
        ("TargetTaxID", "tax_id"),
    ):
        value = row.get(source_key)
        if value is not None:
            target[output_key] = value
    return [target] if target else []


def target_organism(item: JsonObject) -> str:
    organism = object_value(item.get("organism"))
    if organism:
        org = object_value(organism.get("org"))
        if org:
            return first_str(org, "taxname", "common") or ""
    return first_str(item, "organism", "taxname") or ""


def source_id_entries(xref: JsonObject) -> list[JsonValue]:
    return [
        {"type": key, "id": str(value)}
        for key, value in xref.items()
        if isinstance(value, str | int | float)
    ]


def extract_aids(payload: JsonObject) -> set[int]:
    aids: set[int] = set()
    for path in (("IdentifierList", "AID"), ("AIDList", "AID")):
        aids.update(int_values(get_path(payload, path)))
    for item in object_list(get_path(payload, ("InformationList", "Information"))):
        aids.update(int_values(item.get("AID")))
    return aids


def concise_metadata(parsed: JsonObject) -> JsonObject:
    return {
        "aid": parsed.get("aid", 0),
        "name": parsed.get("name", ""),
        "assay_type": parsed.get("assay_type", ""),
        "source_name": parsed.get("source_name", ""),
        "evidence_note": "Assay metadata only; activity rows are assay-specific evidence.",
    }


def copy_keys(target: JsonObject, source: JsonObject, keys: Iterable[str]) -> None:
    for key in keys:
        if key in source:
            target[key] = source[key]


def sources_for_assays(results: list[JsonObject], retrieved_at: str) -> list[JsonValue]:
    sources: list[JsonValue] = []
    seen: set[int] = set()
    for result in results:
        aid = first_int(result, "aid")
        if aid is not None and aid not in seen:
            seen.add(aid)
            sources.append(assay_source(aid, retrieved_at))
    return sources


def assay_source(aid: int, retrieved_at: str) -> JsonObject:
    return {
        "source": "PubChem PUG-REST",
        "identifier": f"AID:{aid}",
        "source_url": f"{PUBCHEM_ASSAY_URL}{aid}",
        "retrieved_at": retrieved_at,
    }


def target_hint_text(value: JsonValue | None) -> str:
    names: list[str] = []
    for item in object_list(value):
        name = item.get("name") or item.get("gene_symbol") or item.get("gene_id")
        if name:
            names.append(str(name))
    return ", ".join(names)


def outcome_counts(rows: list[JsonObject]) -> JsonObject:
    counts: JsonObject = {}
    for row in rows:
        outcome = str(row.get("outcome", "unspecified"))
        current = counts.get(outcome, 0)
        count = current if isinstance(current, int) else 0
        counts[outcome] = count + 1
    return counts


def get_path(value: JsonObject, path: Sequence[str]) -> JsonValue | None:
    current: JsonValue | None = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def object_value(value: JsonValue | None) -> JsonObject | None:
    if isinstance(value, dict):
        return value
    return None


def object_list(value: JsonValue | None) -> list[JsonObject]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def int_values(value: JsonValue | None) -> list[int]:
    if isinstance(value, int):
        return [value]
    if isinstance(value, str) and value.isdecimal():
        return [int(value)]
    if isinstance(value, list):
        values: list[int] = []
        for item in value:
            values.extend(int_values(item))
        return values
    return []


def first_int(row: JsonObject, *keys: str) -> int | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdecimal():
            return int(value)
    return None


def first_str(row: JsonObject, *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, int | float):
            return str(value)
    return None


def text_value(value: JsonValue | None) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n\n".join(part for item in value if (part := text_value(item)))
    if isinstance(value, dict):
        for key in ("string", "String", "text", "value"):
            text = text_value(value.get(key))
            if text:
                return text
    return ""


def pubchem_scalar(value: JsonObject) -> JsonValue:
    for key in ("sval", "fval", "ival", "binary", "bool"):
        scalar = value.get(key)
        if isinstance(scalar, str | int | float | bool):
            return scalar
    return ""


def normalize_outcome(value: JsonValue | None) -> str:
    if isinstance(value, int):
        return OUTCOME_MAP.get(value, str(value))
    if isinstance(value, str):
        return value.lower()
    return ""


def outcome_from_values(values: list[JsonObject]) -> str:
    for value in values:
        if "outcome" in str(value.get("name", "")).lower():
            return str(value.get("value", "")).lower()
    return "unspecified"


def to_snake(value: str) -> str:
    chars: list[str] = []
    for index, char in enumerate(value):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars)


def retrieved_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
