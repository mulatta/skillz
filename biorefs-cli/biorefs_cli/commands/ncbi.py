# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Generic NCBI Entrez escape-hatch commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast

from biorefs_cli.config import load_config
from biorefs_cli.errors import CLIError, ConfigError
from biorefs_cli.ncbi_client import TOOL_NAME, NCBIClient
from biorefs_cli.output import markdown_heading, markdown_table, print_json

if TYPE_CHECKING:
    from biorefs_cli.http import JsonObject

FetchFormat = Literal["json", "xml", "fasta", "genbank", "text"]
JSON_EFETCH_DATABASES = frozenset({"pcassay", "pccompound", "pcsubstance"})


@dataclass(frozen=True, slots=True)
class FetchFormatMapping:
    retmode: str
    rettype: str | None
    native_json: bool = False


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("ncbi", help="Generic NCBI Entrez workflows")
    ncbi_subcommands = parser.add_subparsers(dest="ncbi_command", required=True)

    search = ncbi_subcommands.add_parser("search", help="Search Entrez database")
    search.add_argument("--db", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=positive_int, required=True)
    search.add_argument("--use-history", action="store_true")
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    summary = ncbi_subcommands.add_parser("summary", help="Fetch Entrez summary")
    summary.add_argument("--db", required=True)
    summary.add_argument("--id", required=True)
    summary.add_argument("--json", action="store_true")
    summary.set_defaults(handler=handle)

    fetch = ncbi_subcommands.add_parser("fetch", help="Fetch Entrez record")
    fetch.add_argument("--db", required=True)
    fetch.add_argument("--id", required=True)
    fetch.add_argument(
        "--format",
        choices=("json", "xml", "fasta", "genbank", "text"),
        required=True,
    )
    fetch.add_argument("--raw", action="store_true")
    fetch.set_defaults(handler=handle)

    link = ncbi_subcommands.add_parser("link", help="Fetch Entrez links")
    link.add_argument("--dbfrom", required=True)
    link.add_argument("--db", required=True)
    link.add_argument("--id", required=True)
    link.add_argument("--json", action="store_true")
    link.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    config = load_config()
    if not config.email:
        msg = "NCBI email is required; run biorefs-cli setup --email EMAIL"
        raise ConfigError(msg)
    client = NCBIClient.from_config(config)
    payload = execute(args, client)
    write_output(args, payload)
    return 0


def execute(args: argparse.Namespace, client: NCBIClient) -> object:
    command = cast("str", args.ncbi_command)
    if command == "search":
        return ncbi_search(
            client,
            db=cast("str", args.db),
            query=cast("str", args.query),
            limit=cast("int", args.limit),
            use_history=cast("bool", args.use_history),
        )
    if command == "summary":
        return ncbi_summary(client, db=cast("str", args.db), uid=cast("str", args.id))
    if command == "fetch":
        return ncbi_fetch(
            client,
            db=cast("str", args.db),
            uid=cast("str", args.id),
            output_format=cast("FetchFormat", args.format),
            raw=cast("bool", args.raw),
        )
    if command == "link":
        return ncbi_link(
            client,
            dbfrom=cast("str", args.dbfrom),
            db=cast("str", args.db),
            uid=cast("str", args.id),
        )
    msg = f"unknown ncbi command: {command}"
    raise CLIError(msg, exit_code=2)


def write_output(args: argparse.Namespace, payload: object) -> None:
    command = cast("str", args.ncbi_command)
    if command == "fetch":
        write_fetch_output(args, payload)
        return
    if cast("bool", args.json):
        print_json(payload)
        return
    if command == "search":
        print(markdown_search(cast("dict[str, object]", payload)))
        return
    if command == "summary":
        print(markdown_summary(cast("dict[str, object]", payload)))
        return
    print(markdown_link(cast("dict[str, object]", payload)))


def write_fetch_output(args: argparse.Namespace, payload: object) -> None:
    if cast("bool", args.raw):
        print(cast("str", payload), end="")
        return
    if cast("str", args.format) == "json":
        print_json(payload)
        return
    print(markdown_fetch(cast("str", payload), args))


def ncbi_search(
    client: NCBIClient,
    *,
    db: str,
    query: str,
    limit: int,
    use_history: bool,
) -> dict[str, object]:
    params: dict[str, str | int] = {
        "db": db,
        "term": query,
        "retmode": "json",
        "retmax": limit,
    }
    if use_history:
        params["usehistory"] = "y"
    payload = client.request_json("esearch", params)
    result = object_value(payload.get("esearchresult"))
    output: dict[str, object] = {
        "source": "ncbi",
        "endpoint": "esearch",
        "db": db,
        "query": query,
        "count": int_or_none(result.get("count")),
        "ids": string_list(result.get("idlist")),
        "retstart": int_or_none(result.get("retstart")),
        "retmax": limit,
        "query_translation": str_or_none(result.get("querytranslation")),
        "warnings": result.get("warninglist", {}),
        "provenance": provenance("esearch", "esearch.fcgi"),
    }
    if use_history:
        output["history"] = {
            "webenv": str_or_none(result.get("webenv")),
            "query_key": str_or_none(result.get("querykey")),
        }
    return output


def ncbi_summary(client: NCBIClient, *, db: str, uid: str) -> dict[str, object]:
    payload = client.request_json(
        "esummary",
        {"db": db, "id": uid, "retmode": "json"},
    )
    result = object_value(payload.get("result"))
    records: list[dict[str, object]] = []
    for record_uid in string_list(result.get("uids")):
        source_record = object_value(result.get(record_uid))
        record = dict(source_record)
        record["provenance"] = provenance("esummary", "esummary.fcgi")
        records.append(record)
    return {
        "source": "ncbi",
        "endpoint": "esummary",
        "db": db,
        "id": uid,
        "records": records,
        "provenance": provenance("esummary", "esummary.fcgi"),
    }


def ncbi_fetch(
    client: NCBIClient,
    *,
    db: str,
    uid: str,
    output_format: FetchFormat,
    raw: bool,
) -> str | dict[str, object]:
    mapping = map_fetch_format(db, output_format)
    params = fetch_params(db, uid, mapping)
    if raw:
        return fetch_text(client, params)
    if output_format == "json":
        if mapping.native_json:
            records: object = client.request_json("efetch", params)
            content: dict[str, object] = {"records": records}
        else:
            content = {
                "retmode": mapping.retmode,
                "rettype": mapping.rettype,
                "content": fetch_text(client, params),
            }
        return {
            "source": "ncbi",
            "endpoint": "efetch",
            "db": db,
            "id": uid,
            "format": output_format,
            **content,
            "provenance": provenance("efetch", "efetch.fcgi"),
        }
    return fetch_text(client, params)


def ncbi_link(
    client: NCBIClient,
    *,
    dbfrom: str,
    db: str,
    uid: str,
) -> dict[str, object]:
    payload = client.request_json(
        "elink",
        {"dbfrom": dbfrom, "db": db, "id": uid, "retmode": "json"},
    )
    return {
        "source": "ncbi",
        "endpoint": "elink",
        "dbfrom": dbfrom,
        "db": db,
        "id": uid,
        "linksets": parse_elink_linksets(payload, dbfrom, db),
        "provenance": provenance("elink", "elink.fcgi"),
    }


def fetch_params(
    db: str,
    uid: str,
    mapping: FetchFormatMapping,
) -> dict[str, str | int]:
    params: dict[str, str | int] = {"db": db, "id": uid, "retmode": mapping.retmode}
    if mapping.rettype is not None:
        params["rettype"] = mapping.rettype
    return params


def fetch_text(client: NCBIClient, params: dict[str, str | int]) -> str:
    response = client.http.get(
        client.eutils_url("efetch", params),
        rate_limit_source=client.rate_limit_source(),
    )
    try:
        return response.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = "NCBI returned non-UTF-8 response"
        raise CLIError(msg) from exc


def map_fetch_format(db: str, output_format: FetchFormat) -> FetchFormatMapping:
    normalized_db = db.lower()
    if output_format == "json":
        if normalized_db in JSON_EFETCH_DATABASES:
            return FetchFormatMapping(retmode="json", rettype=None, native_json=True)
        return FetchFormatMapping(retmode="xml", rettype=None, native_json=False)
    if output_format == "xml":
        return FetchFormatMapping(retmode="xml", rettype=None)
    if output_format == "fasta":
        return FetchFormatMapping(retmode="text", rettype="fasta")
    if output_format == "genbank":
        rettype = "gbwithparts" if normalized_db in {"nuccore", "nucleotide"} else "gb"
        return FetchFormatMapping(retmode="text", rettype=rettype)
    return FetchFormatMapping(retmode="text", rettype=None)


def parse_elink_linksets(
    payload: JsonObject,
    dbfrom: str,
    target_db: str,
) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    linksets = payload.get("linksets")
    if not isinstance(linksets, list):
        return groups
    for linkset_value in linksets:
        linkset = object_value(linkset_value)
        source_ids = string_list(linkset.get("ids"))
        linkset_dbs = linkset.get("linksetdbs")
        if not isinstance(linkset_dbs, list):
            continue
        groups.extend(
            parse_elink_group(
                object_value(linkset_db_value),
                source_ids,
                dbfrom,
                target_db,
            )
            for linkset_db_value in linkset_dbs
        )
    return groups


def parse_elink_group(
    linkset_db: dict[str, object],
    source_ids: list[str],
    dbfrom: str,
    target_db: str,
) -> dict[str, object]:
    dbto = str_or_none(linkset_db.get("dbto")) or target_db
    link_name = str_or_none(linkset_db.get("linkname")) or ""
    links = parse_elink_links(linkset_db.get("links"))
    normalized_links = [
        {
            "source_db": dbfrom,
            "source_id": source_ids[0] if len(source_ids) == 1 else None,
            "target_db": dbto,
            "target_id": link["id"],
            "link_name": link_name,
            "score": link["score"],
            "provider": "ncbi-elink",
        }
        for link in links
    ]
    return {
        "source_ids": source_ids,
        "target_db": dbto,
        "link_name": link_name,
        "ids": [link["id"] for link in links],
        "links": normalized_links,
    }


def parse_elink_links(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    links: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            item_id = str_or_none(item.get("id"))
            score = item.get("score")
        else:
            item_id = str(item)
            score = None
        if item_id is not None:
            links.append({"id": item_id, "score": score})
    return links


def markdown_search(payload: dict[str, object]) -> str:
    ids = payload.get("ids")
    id_list = ids if isinstance(ids, list) else []
    lines = [
        markdown_heading("NCBI Search"),
        "",
        f"- DB: {payload.get('db')}",
        f"- Query: {payload.get('query')}",
        f"- Count: {payload.get('count')}",
        f"- Returned: {len(id_list)}",
    ]
    if id_list:
        lines.append(f"- IDs: {', '.join(str(item) for item in id_list[:20])}")
    query_translation = payload.get("query_translation")
    if query_translation:
        lines.append(f"- Query translation: {query_translation}")
    history = payload.get("history")
    if isinstance(history, dict):
        lines.append(f"- History: WebEnv present, query_key={history.get('query_key')}")
    return "\n".join(lines)


def markdown_summary(payload: dict[str, object]) -> str:
    records_value = payload.get("records")
    records = records_value if isinstance(records_value, list) else []
    rows: list[tuple[object, object]] = [
        (
            record.get("uid") or record.get("id") or "",
            record.get("title")
            or record.get("name")
            or record.get("description")
            or "",
        )
        for record in records[:10]
        if isinstance(record, dict)
    ]
    table = markdown_table(("UID", "Title/name"), rows) if rows else "No records."
    return "\n".join(
        [
            markdown_heading("NCBI Summary"),
            "",
            f"- DB: {payload.get('db')}",
            f"- Records: {len(records)}",
            "",
            table,
        ],
    )


def markdown_fetch(content: str, args: argparse.Namespace) -> str:
    language = "xml" if args.format == "xml" else "text"
    trailing_newline = "" if content.endswith("\n") else "\n"
    return "\n".join(
        [
            markdown_heading("NCBI Fetch"),
            "",
            f"- DB: {args.db}",
            f"- ID: {args.id}",
            f"- Format: {args.format}",
            "",
            f"```{language}",
            f"{content}{trailing_newline}```",
        ],
    )


def markdown_link(payload: dict[str, object]) -> str:
    linksets_value = payload.get("linksets")
    linksets = linksets_value if isinstance(linksets_value, list) else []
    rows: list[tuple[object, object, object]] = []
    for linkset in linksets:
        if not isinstance(linkset, dict):
            continue
        ids = linkset.get("ids")
        id_list = ids if isinstance(ids, list) else []
        rows.append(
            (
                linkset.get("link_name") or "",
                len(id_list),
                ", ".join(map(str, id_list[:10])),
            ),
        )
    table = markdown_table(("Link name", "Count", "IDs"), rows) if rows else "No links."
    return "\n".join(
        [
            markdown_heading("NCBI Links"),
            "",
            f"- From: {payload.get('dbfrom')}:{payload.get('id')}",
            f"- To: {payload.get('db')}",
            "",
            table,
        ],
    )


def provenance(endpoint: str, url_path: str) -> dict[str, object]:
    return {
        "source": "ncbi",
        "endpoint": endpoint,
        "url_path": url_path,
        "tool": TOOL_NAME,
        "retrieved_at": datetime.now(UTC).isoformat(),
    }


def object_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def str_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


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
