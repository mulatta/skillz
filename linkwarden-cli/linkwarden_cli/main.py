# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""linkwarden-cli entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from linkwarden_cli.client import Client
from linkwarden_cli.config import load_config, run_token_command, write_config
from linkwarden_cli.errors import CLIError, InputError
from linkwarden_cli.output import (
    emit,
    emit_json,
    emit_table,
    read_json_input,
    response_data,
    short,
    truncate,
)

Handler = Callable[[Client, argparse.Namespace], None]

SORTS = {"newest": 0, "oldest": 1, "name-az": 2, "name-za": 3}
TAG_SORTS = {**SORTS, "count-desc": 4, "count-asc": 5}
TOKEN_EXPIRY = {"7d": 0, "1m": 1, "2m": 2, "3m": 3, "never": 4}


def make_client(config_path: str | None = None) -> Client:
    cfg = load_config(Path(config_path) if config_path else None)
    return Client(cfg.base_url, cfg.token, cfg.timeout)


def cmd_setup(ns: argparse.Namespace) -> None:
    path = write_config(
        ns.base_url, ns.token_command, Path(ns.config) if ns.config else None
    )
    token = run_token_command(ns.token_command)
    print(f"Wrote {path}")
    if token:
        print("Token command works")
    else:
        raise InputError("token_command did not return a token")


def cmd_api(client: Client, ns: argparse.Namespace) -> None:
    method = ns.method.upper()
    body = None
    if ns.body and ns.file:
        raise InputError("use --body or --file, not both")
    if ns.body:
        import json

        try:
            body = json.loads(ns.body)
        except json.JSONDecodeError as exc:
            raise InputError(f"invalid JSON body: {exc}") from None
    elif ns.file:
        body = read_json_input(ns.file)
    query = dict(parse_key_value(item) for item in ns.query)
    if method == "GET":
        result = client.get(ns.path, query=query)
    elif method == "POST":
        result = client.post(ns.path, body, query)
    elif method == "PUT":
        result = client.put(ns.path, body, query)
    elif method == "PATCH":
        result = client.patch(ns.path, body, query)
    elif method == "DELETE":
        result = client.delete(ns.path, body, query)
    else:
        raise InputError(f"unsupported HTTP method: {method}")
    emit_json(result)


def cmd_link_search(client: Client, ns: argparse.Namespace) -> None:
    query = {
        "searchQueryString": ns.query,
        "cursor": ns.cursor,
        "sort": SORTS.get(ns.sort) if ns.sort else None,
    }
    result = client.get("/api/v1/search", query=query)
    emit(result, use_json=ns.use_json, text_fn=print_links)


def cmd_link_get(client: Client, ns: argparse.Namespace) -> None:
    result = client.get(f"/api/v1/links/{ns.id}")
    emit(result, use_json=ns.use_json, text_fn=print_link)


def cmd_link_create(client: Client, ns: argparse.Namespace) -> None:
    body: dict[str, Any] = {"url": ns.url, "type": ns.type}
    put_if(body, "name", ns.name)
    put_if(body, "description", ns.description)
    if ns.collection:
        body["collection"] = collection_ref(client, ns.collection)
    if ns.tag:
        body["tags"] = [{"name": tag} for tag in ns.tag]
    result = client.post("/api/v1/links", body)
    emit(result, use_json=ns.use_json, text_fn=print_link)


def cmd_link_update(client: Client, ns: argparse.Namespace) -> None:
    current = ensure_dict(response_data(client.get(f"/api/v1/links/{ns.id}")))
    body = dict(current)
    body["id"] = int(ns.id)
    put_if(body, "name", ns.name)
    put_if(body, "url", ns.url)
    put_if(body, "description", ns.description)
    if ns.collection:
        collection = collection_ref(client, ns.collection)
        if "id" not in collection:
            raise InputError(
                "link update collection must resolve to an existing collection"
            )
        existing = ensure_dict(
            response_data(client.get(f"/api/v1/collections/{collection['id']}"))
        )
        body["collection"] = {
            "id": existing.get("id"),
            "ownerId": existing.get("ownerId"),
        }
    if ns.tag is not None:
        body["tags"] = [{"name": tag} for tag in ns.tag]
    result = client.put(f"/api/v1/links/{ns.id}", body)
    emit(result, use_json=ns.use_json, text_fn=print_link)


def cmd_link_delete(client: Client, ns: argparse.Namespace) -> None:
    require_yes(ns)
    result = client.delete(f"/api/v1/links/{ns.id}")
    emit(result, use_json=ns.use_json, text_fn=print_deleted)


def cmd_link_archive(client: Client, ns: argparse.Namespace) -> None:
    result = client.put(f"/api/v1/links/{ns.id}/archive")
    emit(result, use_json=ns.use_json, text_fn=print_link)


def cmd_collection_list(client: Client, ns: argparse.Namespace) -> None:
    result = client.get("/api/v1/collections")
    emit(result, use_json=ns.use_json, text_fn=print_collections)


def cmd_collection_get(client: Client, ns: argparse.Namespace) -> None:
    result = client.get(f"/api/v1/collections/{ns.id}")
    emit(result, use_json=ns.use_json, text_fn=print_collection)


def cmd_collection_create(client: Client, ns: argparse.Namespace) -> None:
    body: dict[str, Any] = {"name": ns.name}
    for key in ("description", "color", "icon", "icon_weight"):
        put_if(body, camel(key), getattr(ns, key))
    if ns.parent is not None:
        body["parentId"] = int(ns.parent)
    result = client.post("/api/v1/collections", body)
    emit(result, use_json=ns.use_json, text_fn=print_collection)


def cmd_collection_update(client: Client, ns: argparse.Namespace) -> None:
    current = ensure_dict(response_data(client.get(f"/api/v1/collections/{ns.id}")))
    body = dict(current)
    for key in ("name", "description", "color", "icon", "icon_weight"):
        put_if(body, camel(key), getattr(ns, key))
    if ns.parent is not None:
        body["parentId"] = "root" if ns.parent == "root" else int(ns.parent)
    body.setdefault("members", [])
    result = client.put(f"/api/v1/collections/{ns.id}", body)
    emit(result, use_json=ns.use_json, text_fn=print_collection)


def cmd_collection_delete(client: Client, ns: argparse.Namespace) -> None:
    require_yes(ns)
    result = client.delete(f"/api/v1/collections/{ns.id}")
    emit(result, use_json=ns.use_json, text_fn=print_deleted)


def cmd_tag_list(client: Client, ns: argparse.Namespace) -> None:
    query = {
        "search": ns.search,
        "cursor": ns.cursor,
        "sort": TAG_SORTS.get(ns.sort) if ns.sort else None,
    }
    result = client.get("/api/v1/tags", query=query)
    emit(result, use_json=ns.use_json, text_fn=print_tags)


def cmd_tag_get(client: Client, ns: argparse.Namespace) -> None:
    result = client.get(f"/api/v1/tags/{ns.id}")
    emit(result, use_json=ns.use_json, text_fn=print_tag)


def cmd_tag_create(client: Client, ns: argparse.Namespace) -> None:
    result = client.post(
        "/api/v1/tags", {"tags": [{"label": name} for name in ns.name]}
    )
    emit(result, use_json=ns.use_json, text_fn=print_tags)


def cmd_tag_update(client: Client, ns: argparse.Namespace) -> None:
    result = client.put(f"/api/v1/tags/{ns.id}", {"name": ns.name})
    emit(result, use_json=ns.use_json, text_fn=print_tag)


def cmd_tag_delete(client: Client, ns: argparse.Namespace) -> None:
    require_yes(ns)
    result = client.delete(f"/api/v1/tags/{ns.id}")
    emit(result, use_json=ns.use_json, text_fn=print_deleted)


def cmd_highlight_list(client: Client, ns: argparse.Namespace) -> None:
    result = client.get(f"/api/v1/links/{ns.link_id}/highlights")
    emit(result, use_json=ns.use_json, text_fn=print_highlights)


def cmd_highlight_create(client: Client, ns: argparse.Namespace) -> None:
    body = {
        "linkId": int(ns.link_id),
        "text": ns.text,
        "startOffset": ns.start,
        "endOffset": ns.end,
        "color": ns.color,
        "comment": ns.comment,
    }
    result = client.post("/api/v1/highlights", body)
    emit(result, use_json=ns.use_json, text_fn=print_highlights)


def cmd_highlight_delete(client: Client, ns: argparse.Namespace) -> None:
    require_yes(ns)
    result = client.delete(f"/api/v1/highlights/{ns.id}")
    emit(result, use_json=ns.use_json, text_fn=print_deleted)


def cmd_rss_list(client: Client, ns: argparse.Namespace) -> None:
    result = client.get("/api/v1/rss")
    emit(result, use_json=ns.use_json, text_fn=print_rss)


def cmd_rss_create(client: Client, ns: argparse.Namespace) -> None:
    body: dict[str, Any] = {"name": ns.name, "url": ns.url}
    if ns.collection:
        collection = collection_ref(client, ns.collection)
        body["collectionId"] = collection["id"]
    result = client.post("/api/v1/rss", body)
    emit(result, use_json=ns.use_json, text_fn=print_rss)


def cmd_rss_delete(client: Client, ns: argparse.Namespace) -> None:
    require_yes(ns)
    result = client.delete(f"/api/v1/rss/{ns.id}")
    emit(result, use_json=ns.use_json, text_fn=print_deleted)


def cmd_token_list(client: Client, ns: argparse.Namespace) -> None:
    result = client.get("/api/v1/tokens")
    emit(result, use_json=ns.use_json, text_fn=print_tokens)


def cmd_token_create(client: Client, ns: argparse.Namespace) -> None:
    result = client.post(
        "/api/v1/tokens", {"name": ns.name, "expires": TOKEN_EXPIRY[ns.expires]}
    )
    emit(result, use_json=ns.use_json, text_fn=print_token_created)


def cmd_token_revoke(client: Client, ns: argparse.Namespace) -> None:
    require_yes(ns)
    result = client.delete(f"/api/v1/tokens/{ns.id}")
    emit(result, use_json=ns.use_json, text_fn=print_deleted)


def collection_ref(client: Client, value: str) -> dict[str, Any]:
    try:
        return {"id": int(value)}
    except ValueError:
        pass
    collections = as_list(response_data(client.get("/api/v1/collections")))
    matches = [
        item
        for item in collections
        if str(item.get("name", "")).casefold() == value.casefold()
    ]
    if len(matches) == 1:
        return {"id": matches[0].get("id"), "name": matches[0].get("name")}
    if len(matches) > 1:
        raise InputError(f"collection name is ambiguous: {value}")
    raise InputError(f"collection not found: {value}")


def require_yes(ns: argparse.Namespace) -> None:
    if not ns.yes:
        raise InputError("destructive command requires --yes")


def parse_key_value(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise InputError(f"query item must be KEY=VALUE: {value}")
    key, val = value.split("=", 1)
    if not key:
        raise InputError(f"query key must not be empty: {value}")
    return key, val


def put_if(data: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        data[key] = value


def camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


def ensure_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError("API response did not contain an object")
    return value


def as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("links"), list):
            value = value["links"]
        elif isinstance(value.get("items"), list):
            value = value["items"]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def print_links(data: Any) -> None:
    links = as_list(response_data(data))
    rows = [
        [
            short(x.get("id")),
            truncate(x.get("name") or x.get("url")),
            short(x.get("url")),
        ]
        for x in links
    ]
    emit_table(["ID", "NAME", "URL"], rows)
    payload = response_data(data)
    if isinstance(payload, dict) and payload.get("nextCursor") is not None:
        print(f"nextCursor: {payload['nextCursor']}")


def print_link(data: Any) -> None:
    item = ensure_dict(response_data(data))
    print(f"id: {short(item.get('id'))}")
    print(f"name: {short(item.get('name'))}")
    print(f"url: {short(item.get('url'))}")
    collection = item.get("collection")
    if isinstance(collection, dict):
        print(
            f"collection: {short(collection.get('name'))} ({short(collection.get('id'))})"
        )


def print_collections(data: Any) -> None:
    items = as_list(response_data(data))
    emit_table(
        ["ID", "NAME", "PARENT"],
        [
            [short(x.get("id")), short(x.get("name")), short(x.get("parentId"))]
            for x in items
        ],
    )


def print_collection(data: Any) -> None:
    item = ensure_dict(response_data(data))
    print(f"id: {short(item.get('id'))}")
    print(f"name: {short(item.get('name'))}")
    print(f"description: {short(item.get('description'))}")


def print_tags(data: Any) -> None:
    items = as_list(response_data(data))
    emit_table(
        ["ID", "NAME"],
        [[short(x.get("id")), short(x.get("name") or x.get("label"))] for x in items],
    )


def print_tag(data: Any) -> None:
    item = ensure_dict(response_data(data))
    print(f"id: {short(item.get('id'))}")
    print(f"name: {short(item.get('name'))}")


def print_highlights(data: Any) -> None:
    items = as_list(response_data(data))
    emit_table(
        ["ID", "LINK", "COLOR", "TEXT"],
        [
            [
                short(x.get("id")),
                short(x.get("linkId")),
                short(x.get("color")),
                truncate(x.get("text")),
            ]
            for x in items
        ],
    )


def print_rss(data: Any) -> None:
    items = as_list(response_data(data))
    emit_table(
        ["ID", "NAME", "URL"],
        [
            [short(x.get("id")), short(x.get("name")), short(x.get("url"))]
            for x in items
        ],
    )


def print_tokens(data: Any) -> None:
    items = as_list(response_data(data))
    emit_table(
        ["ID", "NAME", "EXPIRES"],
        [
            [short(x.get("id")), short(x.get("name")), short(x.get("expires"))]
            for x in items
        ],
    )


def print_token_created(data: Any) -> None:
    item = ensure_dict(response_data(data))
    token = item.get("token") or item.get("secretKey") or item.get("secret")
    print(f"id: {short(item.get('id'))}")
    print(f"name: {short(item.get('name'))}")
    if token:
        print("token: (hidden; use --json to print raw response)")


def print_deleted(data: Any) -> None:
    item = response_data(data)
    if isinstance(item, dict):
        ident = item.get("id")
        suffix = f" {ident}" if ident is not None else ""
        print(f"deleted{suffix}")
    elif isinstance(item, str):
        print(item)
    else:
        print("ok")


def add_yes(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--yes", action="store_true", help="Confirm destructive action")


def add_link_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    link = sub.add_parser("link", help="Manage links")
    link_sub = link.add_subparsers(dest="subcmd")
    s = link_sub.add_parser("search")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--cursor", type=int)
    s.add_argument("--sort", choices=sorted(SORTS))
    s.set_defaults(handler=cmd_link_search)
    s = link_sub.add_parser("get")
    s.add_argument("id", type=int)
    s.set_defaults(handler=cmd_link_get)
    s = link_sub.add_parser("create")
    s.add_argument("url")
    s.add_argument("--type", choices=["url", "pdf", "image"], default="url")
    link_fields(s)
    s.set_defaults(handler=cmd_link_create)
    s = link_sub.add_parser("update")
    s.add_argument("id", type=int)
    s.add_argument("--url")
    link_fields(s)
    s.set_defaults(handler=cmd_link_update)
    s = link_sub.add_parser("delete")
    s.add_argument("id", type=int)
    add_yes(s)
    s.set_defaults(handler=cmd_link_delete)
    s = link_sub.add_parser("archive")
    s.add_argument("id", type=int)
    s.set_defaults(handler=cmd_link_archive)


def link_fields(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name")
    parser.add_argument("--description")
    parser.add_argument("--collection")
    parser.add_argument("--tag", action="append")


def add_collection_commands(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    collection = sub.add_parser("collection", help="Manage collections")
    collection_sub = collection.add_subparsers(dest="subcmd")
    for name, handler in (("list", cmd_collection_list),):
        collection_sub.add_parser(name).set_defaults(handler=handler)
    s = collection_sub.add_parser("get")
    s.add_argument("id", type=int)
    s.set_defaults(handler=cmd_collection_get)
    s = collection_sub.add_parser("create")
    s.add_argument("name")
    collection_fields(s)
    s.set_defaults(handler=cmd_collection_create)
    s = collection_sub.add_parser("update")
    s.add_argument("id", type=int)
    collection_fields(s)
    s.set_defaults(handler=cmd_collection_update)
    s = collection_sub.add_parser("delete")
    s.add_argument("id", type=int)
    add_yes(s)
    s.set_defaults(handler=cmd_collection_delete)


def collection_fields(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--description")
    parser.add_argument("--color")
    parser.add_argument("--icon")
    parser.add_argument("--icon-weight")
    parser.add_argument("--parent")


def add_tag_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    tag = sub.add_parser("tag", help="Manage tags")
    tag_sub = tag.add_subparsers(dest="subcmd")
    s = tag_sub.add_parser("list")
    s.add_argument("--search")
    s.add_argument("--cursor", type=int)
    s.add_argument("--sort", choices=sorted(TAG_SORTS))
    s.set_defaults(handler=cmd_tag_list)
    s = tag_sub.add_parser("get")
    s.add_argument("id", type=int)
    s.set_defaults(handler=cmd_tag_get)
    s = tag_sub.add_parser("create")
    s.add_argument("name", nargs="+")
    s.set_defaults(handler=cmd_tag_create)
    s = tag_sub.add_parser("update")
    s.add_argument("id", type=int)
    s.add_argument("name")
    s.set_defaults(handler=cmd_tag_update)
    s = tag_sub.add_parser("delete")
    s.add_argument("id", type=int)
    add_yes(s)
    s.set_defaults(handler=cmd_tag_delete)


def add_highlight_commands(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    highlight = sub.add_parser("highlight", help="Manage highlights")
    highlight_sub = highlight.add_subparsers(dest="subcmd")
    s = highlight_sub.add_parser("list")
    s.add_argument("link_id", type=int)
    s.set_defaults(handler=cmd_highlight_list)
    s = highlight_sub.add_parser("create")
    s.add_argument("link_id", type=int)
    s.add_argument("--text", required=True)
    s.add_argument("--start", required=True, type=int)
    s.add_argument("--end", required=True, type=int)
    s.add_argument("--color", required=True)
    s.add_argument("--comment")
    s.set_defaults(handler=cmd_highlight_create)
    s = highlight_sub.add_parser("delete")
    s.add_argument("id", type=int)
    add_yes(s)
    s.set_defaults(handler=cmd_highlight_delete)


def add_rss_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    rss = sub.add_parser("rss", help="Manage RSS subscriptions")
    rss_sub = rss.add_subparsers(dest="subcmd")
    rss_sub.add_parser("list").set_defaults(handler=cmd_rss_list)
    s = rss_sub.add_parser("create")
    s.add_argument("name")
    s.add_argument("url")
    s.add_argument("--collection")
    s.set_defaults(handler=cmd_rss_create)
    s = rss_sub.add_parser("delete")
    s.add_argument("id", type=int)
    add_yes(s)
    s.set_defaults(handler=cmd_rss_delete)


def add_token_commands(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    token = sub.add_parser("token", help="Manage API tokens")
    token_sub = token.add_subparsers(dest="subcmd")
    token_sub.add_parser("list").set_defaults(handler=cmd_token_list)
    s = token_sub.add_parser("create")
    s.add_argument("name")
    s.add_argument("--expires", required=True, choices=sorted(TOKEN_EXPIRY))
    s.set_defaults(handler=cmd_token_create)
    s = token_sub.add_parser("revoke")
    s.add_argument("id", type=int)
    add_yes(s)
    s.set_defaults(handler=cmd_token_revoke)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkwarden-cli", description="Manage Linkwarden"
    )
    parser.add_argument(
        "-j", "--json", action="store_true", dest="use_json", help="Output JSON"
    )
    parser.add_argument("--config", help="Config JSON path")
    sub = parser.add_subparsers(dest="command")
    s = sub.add_parser("setup", help="Write config and check token command")
    s.add_argument("--base-url", required=True)
    s.add_argument("--token-command", required=True)
    add_link_commands(sub)
    add_collection_commands(sub)
    add_tag_commands(sub)
    add_highlight_commands(sub)
    add_rss_commands(sub)
    add_token_commands(sub)
    s = sub.add_parser("api", help="Call Linkwarden API directly")
    s.add_argument("method")
    s.add_argument("path")
    s.add_argument("--query", action="append", default=[], help="Query item KEY=VALUE")
    s.add_argument("--body", help="JSON request body")
    s.add_argument("--file", help="JSON body file or - for stdin")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    ns = parser.parse_args(argv)
    if not ns.command:
        parser.print_help()
        sys.exit(0)
    try:
        if ns.command == "setup":
            cmd_setup(ns)
            return
        if ns.command == "api":
            cmd_api(make_client(ns.config), ns)
            return
        handler = getattr(ns, "handler", None)
        if handler is None:
            parser.parse_args([ns.command, "--help"])
            return
        handler(make_client(ns.config), ns)
    except CLIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
