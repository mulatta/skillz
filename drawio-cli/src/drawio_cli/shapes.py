from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SOUNDEX_MAP = "01230120022455012623010202"
_TRAIL = re.compile(r"\.*\d*$")
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ShapeEntry:
    id: str
    kind: str
    title: str
    tags: tuple[str, ...]
    libraries: tuple[str, ...]
    style: str
    width: int
    height: int
    template_xml: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ShapeEntry:
        return cls(
            id=str(data.get("id", "")),
            kind=str(data.get("kind", data.get("type", "vertex"))),
            title=str(data.get("title", "")),
            tags=_tags(data.get("tags", ())),
            libraries=tuple(
                str(item)
                for item in data.get(
                    "libraries", ([data["lib"]] if "lib" in data else ())
                )
            ),
            style=str(data.get("style", "")),
            width=int(data.get("width", data.get("w", 0)) or 0),
            height=int(data.get("height", data.get("h", 0)) or 0),
            template_xml=data.get("templateXml"),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "tags": list(self.tags),
            "libraries": list(self.libraries),
            "style": self.style,
            "width": self.width,
            "height": self.height,
            "templateXml": self.template_xml,
        }


@dataclass(frozen=True)
class ShapeIndex:
    entries: tuple[ShapeEntry, ...]


@dataclass(frozen=True)
class SearchResult:
    entries: list[ShapeEntry]
    strong: bool


def _tags(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(
            token for token in re.sub(r"[/,()]", " ", value.lower()).split() if token
        )
    if isinstance(value, list | tuple):
        return tuple(str(item).lower() for item in value if str(item))
    return ()


def soundex(name: str) -> str:
    if not name:
        return ""
    result = [name[0].upper()]
    for char in name[1:]:
        pos = ord(char.upper()) - 65
        if 0 <= pos <= 25:
            code = _SOUNDEX_MAP[pos]
            if code != "0" and code != result[-1]:
                result.append(code)
                if len(result) == 4:
                    break
    result.extend(["0"] * (4 - len(result)))
    return "".join(result[:4])


def split_compound(token: str) -> list[str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", token)
    spaced = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", spaced)
    spaced = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", spaced)
    return [part for part in spaced.lower().split() if len(part) >= 2]


def load_index(path: Path) -> ShapeIndex:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            raw = json.load(handle)
    else:
        with path.open(encoding="utf-8") as handle:
            raw = json.load(handle)
    rows = raw.get("entries", raw) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("shape index must contain list or entries list")
    entries: list[ShapeEntry] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"shape index entry {index} must be an object")
        entries.append(ShapeEntry.from_json(row))
    return ShapeIndex(tuple(entries))


def _build_tag_map(entries: tuple[ShapeEntry, ...]) -> dict[str, set[int]]:
    tag_map: dict[str, set[int]] = {}
    for index, entry in enumerate(entries):
        seen: set[str] = set()
        terms = [*entry.tags, entry.title.lower(), *entry.libraries]
        for raw in terms:
            for token in re.sub(r"[/,()]", " ", raw).split():
                if len(token) < 2 or token in seen:
                    continue
                seen.add(token)
                tag_map.setdefault(token, set()).add(index)
                sx = soundex(_TRAIL.sub("", token))
                if sx and sx != token and sx not in seen:
                    seen.add(sx)
                    tag_map.setdefault(sx, set()).add(index)
    return tag_map


def _terms(query: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in query.split():
        parts = split_compound(raw) or ([raw.lower()] if len(raw) >= 2 else [])
        for part in parts:
            if part not in seen:
                seen.add(part)
                terms.append(part)
    return terms


def _match_term(tag_map: dict[str, set[int]], term: str) -> tuple[set[int], set[int]]:
    exact = set(tag_map.get(term, set()))
    sx = soundex(_TRAIL.sub("", term))
    phonetic = (
        {idx for idx in tag_map.get(sx, set()) if idx not in exact}
        if sx and sx != term
        else set()
    )
    return exact, phonetic


def search_shapes(
    index: ShapeIndex,
    query: str,
    *,
    limit: int = 10,
    library: str | None = None,
    kind: str | None = None,
    fuzzy: bool = False,
) -> SearchResult:
    if limit <= 0:
        raise ValueError("limit must be positive")
    entries = index.entries
    terms = _terms(query)
    if not terms:
        return SearchResult([], strong=False)

    tag_map = _build_tag_map(entries)
    matches = [_match_term(tag_map, term) for term in terms]
    and_set: set[int] | None = None
    for exact, phonetic in matches:
        combined = exact | phonetic
        and_set = combined if and_set is None else and_set & combined
        if not and_set:
            break

    if not and_set and not fuzzy:
        return SearchResult([], strong=False)

    pool = and_set or None
    scores: dict[int, float] = {}
    for exact, phonetic in matches:
        for idx in exact:
            if pool is None or idx in pool:
                scores[idx] = scores.get(idx, 0.0) + 1.0
        for idx in phonetic:
            if idx not in exact and (pool is None or idx in pool):
                scores[idx] = scores.get(idx, 0.0) + 0.5

    def allowed(entry: ShapeEntry) -> bool:
        return (library is None or library in entry.libraries) and (
            kind is None or kind == entry.kind
        )

    term_set = set(terms)

    def title_hits(idx: int) -> int:
        title_tokens = set(_TOKEN_SPLIT.split(entries[idx].title.casefold()))
        return len(term_set & title_tokens)

    ranked = sorted(
        (idx for idx in scores if allowed(entries[idx])),
        key=lambda idx: (
            -scores[idx],
            -title_hits(idx),
            entries[idx].title.casefold(),
            entries[idx].id,
        ),
    )
    result_entries = [entries[idx] for idx in ranked[:limit]]
    strong = bool(result_entries) and bool(and_set) and scores[ranked[0]] >= len(terms)
    return SearchResult(result_entries, strong)
