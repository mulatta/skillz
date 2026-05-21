"""OpenAlex commands."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import quote, unquote, urlencode, urlparse

from biorefs_cli.config import Config, load_config
from biorefs_cli.errors import CLIError, HTTPError
from biorefs_cli.http import HttpClient, JsonObject, JsonValue
from biorefs_cli.output import markdown_heading, markdown_table, print_json

if TYPE_CHECKING:
    import argparse

OPENALEX_BASE_URL = "https://api.openalex.org"
USER_AGENT = "biorefs-cli/0.1 (https://github.com/mulatta/skillz)"
WORK_SELECT = (
    "id,doi,ids,title,display_name,publication_year,publication_date,authorships,"
    "primary_location,best_oa_location,locations,open_access,referenced_works,"
    "referenced_works_count,cited_by_count,related_works,topics,primary_topic,"
    "concepts,is_retracted,is_paratext"
)
OA_SELECT = "id,doi,ids,title,display_name,open_access,best_oa_location,locations"
GRAPH_SELECT = (
    "id,doi,ids,title,display_name,publication_year,cited_by_count,authorships,"
    "primary_location,best_oa_location,open_access,referenced_works,"
    "referenced_works_count,related_works"
)

IdentifierKind = Literal["doi", "pmid", "pmcid", "openalex"]
GraphDirection = Literal["references", "cited-by", "related"]
TrendGroup = Literal["publication-year", "oa-status", "country", "topic"]


@dataclass(frozen=True, slots=True)
class WorkIdentifier:
    kind: IdentifierKind
    value: str
    request_id: str
    identifiers: dict[str, str]


@dataclass(frozen=True, slots=True)
class OpenAlexResponse:
    data: JsonObject
    url: str


@dataclass(frozen=True, slots=True)
class TrendContext:
    query: str
    group_by: TrendGroup
    openalex_group_by: str
    filter_value: str


class OpenAlexClient:
    def __init__(self, *, config: Config, http: HttpClient | None = None) -> None:
        self.config = config
        self.http = http or HttpClient(timeout_seconds=config.timeout_seconds)

    def get_work(self, request_id: str, select: str) -> OpenAlexResponse:
        path_id = quote(request_id, safe=":")
        return self.get(f"/works/{path_id}", {"select": select})

    def list_works(self, params: dict[str, str]) -> OpenAlexResponse:
        return self.get("/works", params)

    def get(self, path: str, params: dict[str, str]) -> OpenAlexResponse:
        url = self.url(path, params)
        data = self.http.get_json(
            url, headers={"User-Agent": USER_AGENT}, rate_limit_source="openalex"
        )
        return OpenAlexResponse(data=data, url=url)

    def url(self, path: str, params: dict[str, str]) -> str:
        request_params = dict(params)
        if self.config.email:
            request_params["mailto"] = self.config.email
        query = urlencode(request_params)
        return (
            f"{OPENALEX_BASE_URL}{path}?{query}"
            if query
            else f"{OPENALEX_BASE_URL}{path}"
        )


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("openalex", help="OpenAlex enrichment workflows")
    openalex_subcommands = parser.add_subparsers(dest="openalex_command", required=True)

    work = openalex_subcommands.add_parser("work", help="Fetch OpenAlex work")
    work.add_argument("--doi")
    work.add_argument("--pmid")
    work.add_argument("--pmcid")
    work.add_argument("--openalex-id")
    work.add_argument("--json", action="store_true")
    work.set_defaults(handler=handle)

    oa = openalex_subcommands.add_parser("oa", help="Fetch OA locations")
    oa.add_argument("--doi")
    oa.add_argument("--pmid")
    oa.add_argument("--pmcid")
    oa.add_argument("--json", action="store_true")
    oa.set_defaults(handler=handle)

    graph = openalex_subcommands.add_parser("graph", help="Fetch citation graph")
    graph.add_argument("--doi")
    graph.add_argument("--pmid")
    graph.add_argument("--openalex-id")
    graph.add_argument("--direction", choices=("references", "cited-by", "related"))
    graph.add_argument("--limit", type=int, default=25)
    graph.add_argument("--json", action="store_true")
    graph.set_defaults(handler=handle)

    trends = openalex_subcommands.add_parser("trends", help="Fetch OpenAlex trends")
    trends.add_argument("query")
    trends.add_argument(
        "--group-by", choices=("publication-year", "oa-status", "country", "topic")
    )
    trends.add_argument("--since", metavar="YEAR", type=int)
    trends.add_argument("--until", metavar="YEAR", type=int)
    trends.add_argument("--json", action="store_true")
    trends.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    try:
        result = run(args, OpenAlexClient(config=load_config()))
    except HTTPError:
        raise
    except CLIError:
        raise
    except ValueError as exc:
        command = getattr(args, "openalex_command", "unknown")
        message = f"openalex {command}: {exc}"
        raise CLIError(message, exit_code=2) from exc
    if getattr(args, "json", False):
        print_json(result)
    else:
        print(format_markdown(result))
    return 0


def run(args: argparse.Namespace, client: OpenAlexClient) -> JsonObject:
    command = str(args.openalex_command)
    if command == "work":
        identifier = identifier_from_args(args, allow_pmcid=True)
        response = client.get_work(identifier.request_id, WORK_SELECT)
        return parse_work_result(response, identifier)
    if command == "oa":
        identifier = identifier_from_args(args, allow_pmcid=True)
        response = client.get_work(identifier.request_id, OA_SELECT)
        return parse_oa_result(response, identifier)
    if command == "graph":
        identifier = identifier_from_args(args, allow_pmcid=False)
        direction = require_direction(args.direction)
        limit = require_positive_limit(args.limit)
        return graph_result(client, identifier, direction, limit)
    if command == "trends":
        group_by = require_group_by(args.group_by)
        return trends_result(
            client,
            query=str(args.query),
            group_by=group_by,
            since=cast("int | None", args.since),
            until=cast("int | None", args.until),
        )
    msg = f"unsupported subcommand: {command}"
    raise ValueError(msg)


def identifier_from_args(
    args: argparse.Namespace, *, allow_pmcid: bool
) -> WorkIdentifier:
    selected: list[tuple[IdentifierKind, str]] = []
    for attr, kind in (
        ("doi", "doi"),
        ("pmid", "pmid"),
        ("pmcid", "pmcid"),
        ("openalex_id", "openalex"),
    ):
        if kind == "pmcid" and not allow_pmcid:
            continue
        value = getattr(args, attr, None)
        if value is not None:
            selected.append((cast("IdentifierKind", kind), str(value)))
    if len(selected) != 1:
        msg = "pass exactly one work identifier"
        raise ValueError(msg)
    kind, value = selected[0]
    return normalize_work_identifier(kind, value)


def normalize_work_identifier(kind: IdentifierKind, value: str) -> WorkIdentifier:
    if kind == "doi":
        doi = strip_doi(value)
        if not doi.startswith("10.") or "/" not in doi:
            msg = f"malformed DOI: {value}"
            raise ValueError(msg)
        return WorkIdentifier(
            kind="doi",
            value=doi,
            request_id=f"doi:{doi}",
            identifiers={"doi": doi, "doi_url": f"https://doi.org/{doi}"},
        )
    if kind == "pmid":
        pmid = strip_pmid(value)
        if not pmid.isdigit():
            msg = f"malformed PMID: {value}"
            raise ValueError(msg)
        return WorkIdentifier(
            kind="pmid",
            value=pmid,
            request_id=f"pmid:{pmid}",
            identifiers={"pmid": pmid},
        )
    if kind == "pmcid":
        pmcid = strip_pmcid(value)
        if not (pmcid.startswith("PMC") and pmcid[3:].isdigit()):
            msg = f"malformed PMCID: {value}"
            raise ValueError(msg)
        return WorkIdentifier(
            kind="pmcid",
            value=pmcid,
            request_id=f"pmcid:{pmcid}",
            identifiers={"pmcid": pmcid},
        )
    openalex_id = strip_openalex_id(value)
    if not (openalex_id.startswith("W") and openalex_id[1:].isdigit()):
        msg = f"malformed OpenAlex work ID: {value}"
        raise ValueError(msg)
    return WorkIdentifier(
        kind="openalex",
        value=openalex_id,
        request_id=openalex_id,
        identifiers={
            "openalex_id": openalex_id,
            "openalex_url": f"https://openalex.org/{openalex_id}",
        },
    )


def strip_doi(value: str) -> str:
    normalized = unquote(value.strip().rstrip("."))
    lowered = normalized.lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if lowered.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized.strip().lower()


def strip_pmid(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.netloc.lower() == "pubmed.ncbi.nlm.nih.gov":
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            normalized = parts[0]
    if normalized.lower().startswith("pmid:"):
        normalized = normalized[5:]
    return normalized.strip()


def strip_pmcid(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if "ncbi.nlm.nih.gov" in parsed.netloc.lower():
        parts = [part for part in parsed.path.split("/") if part]
        matches = [
            part
            for part in parts
            if part.upper().startswith("PMC") and part[3:].isdigit()
        ]
        if matches:
            normalized = matches[0]
    if normalized.lower().startswith("pmcid:"):
        normalized = normalized[6:]
    return normalized.strip().upper()


def strip_openalex_id(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.netloc.lower() == "openalex.org":
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            normalized = parts[-1]
    if normalized.lower().startswith("openalex:"):
        normalized = normalized[9:]
    return normalized.strip().upper()


def require_direction(value: object) -> GraphDirection:
    if value in {"references", "cited-by", "related"}:
        return cast("GraphDirection", value)
    msg = "--direction is required"
    raise ValueError(msg)


def require_group_by(value: object) -> TrendGroup:
    if value in {"publication-year", "oa-status", "country", "topic"}:
        return cast("TrendGroup", value)
    msg = "--group-by is required"
    raise ValueError(msg)


def require_positive_limit(value: object) -> int:
    if value is None:
        limit = 25
    elif isinstance(value, int):
        limit = value
    elif isinstance(value, str):
        limit = int(value)
    else:
        msg = "--limit must be an integer"
        raise ValueError(msg)
    if limit < 1:
        msg = "--limit must be greater than 0"
        raise ValueError(msg)
    return limit


def parse_work_result(
    response: OpenAlexResponse, identifier: WorkIdentifier
) -> JsonObject:
    work = parse_work(response.data)
    identifiers = merge_identifiers(
        identifier.identifiers, as_object(work["identifiers"])
    )
    return as_json_object(
        {
            "kind": "openalex.work",
            "identifiers": identifiers,
            "work": work,
            "sources": [source_entry(response.url, "openalex.works")],
            "warnings": work_warnings(work),
            "missing": work_missing(work),
        }
    )


def parse_work(data: JsonObject) -> JsonObject:
    identifiers = identifiers_from_work(data)
    return as_json_object(
        {
            "source": "openalex",
            "identifiers": identifiers,
            "openalex_id": identifiers.get("openalex_id"),
            "openalex_url": identifiers.get("openalex_url"),
            "doi": identifiers.get("doi"),
            "doi_url": identifiers.get("doi_url"),
            "pmid": identifiers.get("pmid"),
            "pmcid": identifiers.get("pmcid"),
            "title": first_string(data, ("title", "display_name")),
            "publication_year": data.get("publication_year"),
            "publication_date": data.get("publication_date"),
            "venue": parse_source(
                as_object(data.get("primary_location")).get("source")
            ),
            "authors": parse_authors(data.get("authorships")),
            "institutions": parse_work_institutions(data.get("authorships")),
            "topics": parse_topics(data),
            "concepts": parse_concepts(data.get("concepts")),
            "cited_by_count": data.get("cited_by_count", 0),
            "referenced_works_count": referenced_works_count(data),
            "referenced_works": [
                short_openalex_id(item)
                for item in string_list(data.get("referenced_works"))
            ],
            "related_works": [
                short_openalex_id(item)
                for item in string_list(data.get("related_works"))
            ],
            "open_access": parse_open_access(data.get("open_access")),
            "locations_summary": locations_summary(data),
            "flags": {
                "is_retracted": data.get("is_retracted", False),
                "is_paratext": data.get("is_paratext", False),
            },
            "provenance": {"api": "openalex", "endpoint": "/works/{id}"},
        }
    )


def parse_oa_result(
    response: OpenAlexResponse, identifier: WorkIdentifier
) -> JsonObject:
    identifiers = merge_identifiers(
        identifier.identifiers, identifiers_from_work(response.data)
    )
    open_access = parse_open_access(response.data.get("open_access"))
    best_locations = parse_oa_locations(
        [response.data.get("best_oa_location")], "openalex.best_oa_location"
    )
    locations = parse_oa_locations(response.data.get("locations"), "openalex.locations")
    warnings: list[JsonValue] = []
    missing: list[JsonValue] = []
    if open_access.get("is_oa") is not True:
        warnings.append("closed-access")
    if not locations and not best_locations:
        missing.append("locations")
    return as_json_object(
        {
            "kind": "openalex.oa",
            "identifiers": identifiers,
            "title": first_string(response.data, ("title", "display_name")),
            "open_access": open_access,
            "oa_status": open_access.get("oa_status"),
            "best_oa_location": best_locations[0] if best_locations else None,
            "locations": locations,
            "sources": [source_entry(response.url, "openalex.oa")],
            "warnings": warnings,
            "missing": missing,
        }
    )


def graph_result(
    client: OpenAlexClient,
    identifier: WorkIdentifier,
    direction: GraphDirection,
    limit: int,
) -> JsonObject:
    target_response = client.get_work(identifier.request_id, GRAPH_SELECT)
    target = parse_work(target_response.data)
    target_id = str(target.get("openalex_id") or identifier.value)
    if direction == "cited-by":
        listed = client.list_works(
            {
                "filter": f"cites:{target_id}",
                "select": GRAPH_SELECT,
                "sort": "-cited_by_count",
                "per_page": str(limit),
            }
        )
        works = [parse_work(item) for item in object_list(listed.data.get("results"))]
        edges = [
            edge(str(work.get("openalex_id")), target_id, direction) for work in works
        ]
        source_url = listed.url
        truncated = is_truncated(listed.data, limit)
    else:
        field = "referenced_works" if direction == "references" else "related_works"
        ids = [
            work_id
            for work_id in (
                short_openalex_id(item)
                for item in string_list(target_response.data.get(field))
            )
            if work_id is not None
        ]
        selected_ids = ids[:limit]
        works = hydrate_works(client, selected_ids)
        edges = [edge(target_id, work_id, direction) for work_id in selected_ids]
        source_url = target_response.url
        truncated = len(ids) > limit
    nodes = [target, *works]
    return as_json_object(
        {
            "kind": "openalex.graph",
            "identifiers": merge_identifiers(
                identifier.identifiers, as_object(target["identifiers"])
            ),
            "query": as_json_object(dict(identifier.identifiers)),
            "direction": direction,
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "unavailable": [
                node for node in nodes if node.get("status") == "unavailable"
            ],
            "sources": [source_entry(source_url, graph_provenance(direction))],
            "warnings": [],
            "missing": [] if edges else ["edges"],
        }
    )


def hydrate_works(client: OpenAlexClient, ids: list[str]) -> list[JsonObject]:
    if not ids:
        return []
    results: dict[str, JsonObject] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(client.get_work, work_id, GRAPH_SELECT): work_id
            for work_id in ids
        }
        for future in as_completed(futures):
            work_id = futures[future]
            try:
                results[work_id] = parse_work(future.result().data)
            except HTTPError:
                results[work_id] = unavailable_work(work_id)
    return [results[work_id] for work_id in ids]


def trends_result(
    client: OpenAlexClient,
    *,
    query: str,
    group_by: TrendGroup,
    since: int | None,
    until: int | None,
) -> JsonObject:
    if since is not None and until is not None and since > until:
        msg = "--since must be less than or equal to --until"
        raise ValueError(msg)
    openalex_group_by = trend_group_to_openalex(group_by)
    filter_value = trend_filter(since, until)
    response = client.list_works(
        {"search": query, "filter": filter_value, "group_by": openalex_group_by}
    )
    context = TrendContext(
        query=query,
        group_by=group_by,
        openalex_group_by=openalex_group_by,
        filter_value=filter_value,
    )
    return parse_trends_response(response, context)


def parse_trends_response(
    response: OpenAlexResponse, context: TrendContext
) -> JsonObject:
    rows = [
        parse_trend_bucket(item) for item in object_list(response.data.get("group_by"))
    ]
    return as_json_object(
        {
            "kind": "openalex.trends",
            "identifiers": {},
            "query": context.query,
            "group_by": context.group_by,
            "openalex_group_by": context.openalex_group_by,
            "filters": context.filter_value,
            "rows": rows,
            "sources": [source_entry(response.url, "openalex.group_by")],
            "warnings": [],
            "missing": [] if rows else ["rows"],
        }
    )


def parse_trend_bucket(bucket: JsonObject) -> JsonObject:
    return as_json_object(
        {
            "key": bucket.get("key"),
            "display_name": bucket.get("key_display_name"),
            "count": bucket.get("count", 0),
            "provenance": "openalex.group_by",
        }
    )


def parse_authors(value: JsonValue) -> list[JsonObject]:
    authors: list[JsonObject] = []
    for authorship in object_list(value):
        author = as_object(authorship.get("author"))
        authors.append(
            as_json_object(
                {
                    "name": author.get("display_name"),
                    "openalex_id": short_openalex_id(str_or_none(author.get("id"))),
                    "orcid": author.get("orcid"),
                    "position": authorship.get("author_position"),
                    "is_corresponding": authorship.get("is_corresponding"),
                    "institutions": parse_institutions(authorship.get("institutions")),
                }
            )
        )
    return authors


def parse_work_institutions(value: JsonValue) -> list[JsonObject]:
    seen: set[str] = set()
    institutions: list[JsonObject] = []
    for authorship in object_list(value):
        for institution in parse_institutions(authorship.get("institutions")):
            key = str(institution.get("openalex_id") or institution.get("name"))
            if key not in seen:
                seen.add(key)
                institutions.append(institution)
    return institutions


def parse_institutions(value: JsonValue) -> list[JsonObject]:
    return [
        as_json_object(
            {
                "openalex_id": short_openalex_id(str_or_none(institution.get("id"))),
                "name": institution.get("display_name"),
                "ror": institution.get("ror"),
                "country_code": institution.get("country_code"),
            }
        )
        for institution in object_list(value)
    ]


def parse_topics(data: JsonObject) -> list[JsonObject]:
    raw_topics = object_list(data.get("topics"))
    primary = as_optional_object(data.get("primary_topic"))
    if primary is not None and primary not in raw_topics:
        raw_topics = [primary, *raw_topics]
    return [
        as_json_object(
            {
                "openalex_id": short_openalex_id(str_or_none(topic.get("id"))),
                "display_name": topic.get("display_name"),
                "score": topic.get("score"),
                "subfield": topic.get("subfield"),
                "field": topic.get("field"),
                "domain": topic.get("domain"),
            }
        )
        for topic in raw_topics
    ]


def parse_concepts(value: JsonValue) -> list[JsonObject]:
    return [
        as_json_object(
            {
                "openalex_id": short_openalex_id(str_or_none(concept.get("id"))),
                "display_name": concept.get("display_name"),
                "score": concept.get("score"),
                "level": concept.get("level"),
            }
        )
        for concept in object_list(value)
    ]


def parse_source(value: JsonValue) -> JsonObject | None:
    source = as_optional_object(value)
    if source is None:
        return None
    return as_json_object(
        {
            "openalex_id": short_openalex_id(str_or_none(source.get("id"))),
            "display_name": source.get("display_name"),
            "issn_l": source.get("issn_l"),
            "issn": string_list(source.get("issn")),
            "type": source.get("type"),
            "is_oa": source.get("is_oa"),
            "is_in_doaj": source.get("is_in_doaj"),
            "host_organization_name": source.get("host_organization_name"),
        }
    )


def parse_open_access(value: JsonValue) -> JsonObject:
    data = as_object(value)
    return as_json_object(
        {
            "is_oa": data.get("is_oa", False),
            "oa_status": data.get("oa_status"),
            "oa_url": data.get("oa_url"),
            "any_repository_has_fulltext": data.get("any_repository_has_fulltext"),
        }
    )


def parse_oa_locations(value: JsonValue, provenance: str) -> list[JsonObject]:
    raw_locations = value if isinstance(value, list) else [value]
    locations: list[JsonObject] = []
    for raw_location in raw_locations:
        location = as_optional_object(raw_location)
        if location is None or location.get("is_oa") is not True:
            continue
        source = parse_source(location.get("source"))
        pdf_url = str_or_none(location.get("pdf_url"))
        landing_url = str_or_none(location.get("landing_page_url"))
        if pdf_url is not None:
            locations.append(oa_location(location, source, pdf_url, "pdf", provenance))
        if landing_url is not None:
            locations.append(
                oa_location(location, source, landing_url, "landing-page", provenance)
            )
    return locations


def oa_location(
    location: JsonObject,
    source: JsonObject | None,
    url: str,
    url_type: str,
    provenance: str,
) -> JsonObject:
    return as_json_object(
        {
            "url": url,
            "url_type": url_type,
            "is_oa": location.get("is_oa", False),
            "license": location.get("license"),
            "license_id": location.get("license_id"),
            "version": location.get("version"),
            "source": source,
            "provenance": provenance,
        }
    )


def identifiers_from_work(data: JsonObject) -> JsonObject:
    ids = as_object(data.get("ids"))
    openalex_url = first_string(data, ("id",)) or str_or_none(ids.get("openalex"))
    openalex_id = short_openalex_id(openalex_url)
    doi = normalize_output_doi(
        first_string(data, ("doi",)) or str_or_none(ids.get("doi"))
    )
    pmid = normalize_output_pmid(str_or_none(ids.get("pmid")))
    pmcid = normalize_output_pmcid(str_or_none(ids.get("pmcid")))
    result: JsonObject = {}
    if openalex_id is not None:
        result["openalex_id"] = openalex_id
        result["openalex_url"] = f"https://openalex.org/{openalex_id}"
    if doi is not None:
        result["doi"] = doi
        result["doi_url"] = f"https://doi.org/{doi}"
    if pmid is not None:
        result["pmid"] = pmid
    if pmcid is not None:
        result["pmcid"] = pmcid
    return result


def locations_summary(data: JsonObject) -> JsonObject:
    locations = object_list(data.get("locations"))
    oa_locations = [item for item in locations if item.get("is_oa") is True]
    best = as_optional_object(data.get("best_oa_location"))
    return as_json_object(
        {
            "count": len(locations),
            "oa_count": len(oa_locations),
            "has_best_oa_location": best is not None,
            "best_oa_source": parse_source(best.get("source")) if best else None,
        }
    )


def referenced_works_count(data: JsonObject) -> int:
    count = data.get("referenced_works_count")
    if isinstance(count, int):
        return count
    return len(string_list(data.get("referenced_works")))


def edge(source: str, target: str, direction: GraphDirection) -> JsonObject:
    return as_json_object(
        {
            "source": source,
            "target": target,
            "direction": direction,
            "provenance": graph_provenance(direction),
            "evidence": "algorithmic" if direction == "related" else "citation-graph",
        }
    )


def unavailable_work(work_id: str) -> JsonObject:
    return as_json_object(
        {
            "status": "unavailable",
            "reason": "not-found",
            "source": "openalex",
            "openalex_id": work_id,
            "identifiers": {"openalex_id": work_id},
        }
    )


def graph_provenance(direction: GraphDirection) -> str:
    if direction == "references":
        return "openalex.referenced_works"
    if direction == "cited-by":
        return "openalex.filter.cites"
    return "openalex.related_works"


def trend_group_to_openalex(group_by: TrendGroup) -> str:
    mapping = {
        "publication-year": "publication_year",
        "oa-status": "open_access.oa_status",
        "country": "authorships.institutions.country_code",
        "topic": "primary_topic.id",
    }
    return mapping[group_by]


def trend_filter(since: int | None, until: int | None) -> str:
    filters = ["type:article"]
    if since is not None:
        filters.append(f"publication_year:>{since - 1}")
    if until is not None:
        filters.append(f"publication_year:<{until + 1}")
    return ",".join(filters)


def is_truncated(data: JsonObject, limit: int) -> bool:
    meta = as_object(data.get("meta"))
    count = meta.get("count")
    return isinstance(count, int) and count > limit


def source_entry(url: str, provenance: str) -> JsonObject:
    return {"name": "openalex", "url": url, "provenance": provenance}


def work_warnings(work: JsonObject) -> list[JsonValue]:
    warnings: list[JsonValue] = []
    if as_object(work.get("open_access")).get("is_oa") is not True:
        warnings.append("closed-access")
    return warnings


def work_missing(work: JsonObject) -> list[JsonValue]:
    missing: list[JsonValue] = []
    if work.get("title") is None:
        missing.append("title")
    if work.get("publication_year") is None:
        missing.append("publication_year")
    identifiers = as_object(work.get("identifiers"))
    if not any(key in identifiers for key in ("doi", "pmid", "pmcid")):
        missing.append("external_identifiers")
    return missing


def merge_identifiers(
    first: dict[str, str] | JsonObject, second: JsonObject
) -> JsonObject:
    result: JsonObject = dict(first)
    result.update(second)
    return result


def first_string(data: JsonObject, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = str_or_none(data.get(key))
        if value is not None:
            return value
    return None


def as_json_object(value: dict[str, object]) -> JsonObject:
    return cast("JsonObject", value)


def str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def string_list(value: JsonValue) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def object_list(value: JsonValue) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def as_object(value: JsonValue) -> JsonObject:
    return value if isinstance(value, dict) else {}


def as_optional_object(value: JsonValue) -> JsonObject | None:
    return value if isinstance(value, dict) else None


def short_openalex_id(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.netloc.lower() == "openalex.org":
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            return parts[-1].upper()
    if value.lower().startswith("openalex:"):
        return value[9:].upper()
    return value.upper()


def normalize_output_doi(value: str | None) -> str | None:
    if value is None:
        return None
    doi = strip_doi(value)
    return doi if doi.startswith("10.") and "/" in doi else None


def normalize_output_pmid(value: str | None) -> str | None:
    if value is None:
        return None
    pmid = strip_pmid(value)
    return pmid if pmid.isdigit() else None


def normalize_output_pmcid(value: str | None) -> str | None:
    if value is None:
        return None
    pmcid = strip_pmcid(value)
    return pmcid if pmcid.startswith("PMC") and pmcid[3:].isdigit() else None


def format_markdown(result: JsonObject) -> str:
    kind = result.get("kind")
    if kind == "openalex.work":
        return format_work_markdown(result)
    if kind == "openalex.oa":
        return format_oa_markdown(result)
    if kind == "openalex.graph":
        return format_graph_markdown(result)
    if kind == "openalex.trends":
        return format_trends_markdown(result)
    return str(result)


def format_work_markdown(result: JsonObject) -> str:
    work = as_object(result.get("work"))
    open_access = as_object(work.get("open_access"))
    lines = [markdown_heading(display(work.get("title"))), ""]
    lines.extend(identifier_lines(as_object(result.get("identifiers"))))
    lines.extend(
        [
            f"- Year: {display(work.get('publication_year'))}",
            f"- Venue/source: {display(as_object(work.get('venue')).get('display_name'))}",
            f"- Cited by: {display(work.get('cited_by_count'))}",
            f"- References: {display(work.get('referenced_works_count'))}",
            f"- OA status: {display(open_access.get('oa_status'))}",
        ]
    )
    authors = object_list(work.get("authors"))
    if authors:
        names = [display(author.get("name")) for author in authors[:8]]
        suffix = " et al." if len(authors) > 8 else ""
        lines.append(f"- Authors: {', '.join(names)}{suffix}")
    topics = object_list(work.get("topics"))
    if topics:
        names = [display(topic.get("display_name")) for topic in topics[:5]]
        lines.append(f"- Topics: {', '.join(names)}")
    lines.append("\nSource: OpenAlex metadata; not source-of-record full text.")
    return "\n".join(lines)


def format_oa_markdown(result: JsonObject) -> str:
    lines = [markdown_heading("OpenAlex OA locations"), ""]
    lines.extend(identifier_lines(as_object(result.get("identifiers"))))
    lines.append(f"- OA status: {display(result.get('oa_status'))}")
    locations = object_list(result.get("locations"))
    if not locations:
        lines.append("\nNo candidate OA locations from OpenAlex.")
    else:
        rows = [
            (
                location.get("url_type"),
                location.get("version"),
                location.get("license"),
                location.get("url"),
            )
            for location in locations
        ]
        lines.extend(["", markdown_table(("Type", "Version", "License", "URL"), rows)])
    lines.append("\nOpenAlex discovers OA candidates only; no full text fetched.")
    return "\n".join(lines)


def format_graph_markdown(result: JsonObject) -> str:
    lines = [
        markdown_heading(f"OpenAlex graph: {display(result.get('direction'))}"),
        "",
    ]
    edges = object_list(result.get("edges"))
    if not edges:
        lines.append("No edges found.")
    else:
        rows = [
            (
                edge_item.get("source"),
                edge_item.get("target"),
                edge_item.get("provenance"),
            )
            for edge_item in edges
        ]
        lines.append(markdown_table(("Source", "Target", "Provenance"), rows))
    if result.get("truncated") is True:
        lines.append("\nTruncated by --limit.")
    return "\n".join(lines)


def format_trends_markdown(result: JsonObject) -> str:
    rows = [
        (row.get("key"), row.get("display_name"), row.get("count"))
        for row in object_list(result.get("rows"))
    ]
    return "\n".join(
        [
            markdown_heading(f"OpenAlex trends: {display(result.get('query'))}"),
            "",
            markdown_table(("Key", "Display name", "Count"), rows),
        ]
    )


def identifier_lines(identifiers: JsonObject) -> list[str]:
    lines: list[str] = []
    for label, key in (
        ("OpenAlex", "openalex_id"),
        ("DOI", "doi"),
        ("PMID", "pmid"),
        ("PMCID", "pmcid"),
    ):
        value = identifiers.get(key)
        if value is not None:
            lines.append(f"- {label}: {value}")
    return lines


def display(value: object) -> str:
    return "unknown" if value is None else str(value)
