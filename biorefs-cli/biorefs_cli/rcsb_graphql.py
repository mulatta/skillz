"""Batch PDB entry metadata from the RCSB Data GraphQL endpoint.

One POST enriches a page of search hits with title, method, resolution, and
organism — turning bare PDB ids into a usable ranked table without an N+1 storm
of per-entry REST calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from biorefs_cli.config import Config

GRAPHQL_URL = "https://data.rcsb.org/graphql"
USER_AGENT = "biorefs-cli/0.1 (https://github.com/mulatta/skillz)"
ENTRY_FIELDS = (
    "rcsb_id struct{title} exptl{method} "
    "rcsb_entry_info{resolution_combined} "
    "polymer_entities{rcsb_entity_source_organism{scientific_name}}"
)


@dataclass(frozen=True, slots=True)
class EntryMeta:
    pdb_id: str
    title: str | None
    method: str | None
    resolution: float | None
    organisms: list[str]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "method": self.method,
            "resolution": self.resolution,
            "organisms": self.organisms,
        }


class MetadataBackend(Protocol):
    def entry_metadata(self, ids: list[str]) -> dict[str, EntryMeta]: ...


class RcsbGraphQLClient:
    def __init__(self, *, config: Config, http: object | None = None) -> None:
        from biorefs_cli.http import HttpClient

        self.http = cast(
            "HttpClient", http or HttpClient(timeout_seconds=config.timeout_seconds)
        )

    def entry_metadata(self, ids: list[str]) -> dict[str, EntryMeta]:
        if not ids:
            return {}
        payload = cast(
            "dict[str, object]",
            self.http.post_json(
                GRAPHQL_URL,
                build_query(ids),
                headers={"User-Agent": USER_AGENT},
                rate_limit_source="rcsb",
            ),
        )
        return parse_entries(payload)


def build_query(ids: list[str]) -> dict[str, object]:
    id_list = ",".join(f'"{pdb_id}"' for pdb_id in ids)
    return {"query": f"{{entries(entry_ids:[{id_list}]){{{ENTRY_FIELDS}}}}}"}


def parse_entries(payload: dict[str, object]) -> dict[str, EntryMeta]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    entries = data.get("entries")
    if not isinstance(entries, list):
        return {}
    result: dict[str, EntryMeta] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        pdb_id = optional_str(entry, "rcsb_id")
        if pdb_id is None:
            continue
        result[pdb_id] = parse_entry(pdb_id, entry)
    return result


def parse_entry(pdb_id: str, entry: dict[str, object]) -> EntryMeta:
    struct = object_or_none(entry, "struct")
    info = object_or_none(entry, "rcsb_entry_info")
    return EntryMeta(
        pdb_id=pdb_id,
        title=optional_str(struct, "title") if struct else None,
        method=methods(entry),
        resolution=first_resolution(info) if info else None,
        organisms=organisms(entry),
    )


def methods(entry: dict[str, object]) -> str | None:
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


def organisms(entry: dict[str, object]) -> list[str]:
    found: list[str] = []
    for polymer in object_list(entry, "polymer_entities"):
        for organism in object_list(polymer, "rcsb_entity_source_organism"):
            name = optional_str(organism, "scientific_name")
            if name is not None and name not in found:
                found.append(name)
    return found


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


def optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None
