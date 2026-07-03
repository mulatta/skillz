"""Command line interface for Miniflux."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from miniflux_cli.client import MinifluxClient, MinifluxError, resolve_category_id
from miniflux_cli.config import (
    ConfigError,
    check_token_command,
    load_config,
    write_config,
    xdg_cache_home,
)
from miniflux_cli.markdown import entry_to_markdown


def build_client(args: argparse.Namespace) -> MinifluxClient:
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)
    return MinifluxClient(api_url=config.api_url, token=config.token)


def cmd_setup(args: argparse.Namespace) -> int:
    config_path = Path(args.config) if args.config else None
    path = write_config(args.api_url, args.token_command, config_path)
    print(f"Wrote {path}")
    if check_token_command(args.token_command):
        print("Token command works")
    else:
        print("Warning: token command did not return a token", file=sys.stderr)
    return 0


def cmd_list_categories(args: argparse.Namespace) -> int:
    client = build_client(args)
    categories = client.categories()
    if wants_json(args):
        print_json(categories)
    else:
        print_table(categories, ["id", "title"])
    return 0


def cmd_list_feeds(args: argparse.Namespace) -> int:
    client = build_client(args)
    feeds = client.feeds()
    category_id = resolve_category_id(client, args.category)
    if category_id is not None:
        feeds = [feed for feed in feeds if _feed_category_id(feed) == category_id]
    if wants_json(args):
        print_json(feeds)
    else:
        rows = [
            {
                "id": feed.get("id", ""),
                "title": feed.get("title", ""),
                "category": _feed_category_title(feed),
                "site_url": feed.get("site_url", ""),
            }
            for feed in feeds
        ]
        print_table(rows, ["id", "title", "category", "site_url"])
    return 0


def cmd_list_entries(args: argparse.Namespace) -> int:
    client = build_client(args)
    entries = fetch_entries(client, args)
    if wants_json(args):
        print_json(entries)
    else:
        rows = [_entry_row(entry) for entry in entries]
        print_table(rows, ["id", "starred", "category", "feed", "title"])
    return 0


def cmd_list_enclosures(args: argparse.Namespace) -> int:
    client = build_client(args)
    entry = client.entry(args.entry_id)
    enclosures = _enclosures(entry)
    if wants_json(args):
        print_json(enclosures)
    else:
        rows = [
            {
                "idx": idx,
                "mime_type": enclosure.get("mime_type", ""),
                "url": enclosure.get("url", ""),
            }
            for idx, enclosure in enumerate(enclosures)
        ]
        print_table(rows, ["idx", "mime_type", "url"])
    return 0


def cmd_show_entry(args: argparse.Namespace) -> int:
    client = build_client(args)
    entry = client.entry(args.entry_id)
    if wants_json(args):
        print_json(entry)
    else:
        print(entry_to_markdown(entry), end="")
    return 0


def cmd_fetch_enclosure(args: argparse.Namespace) -> int:
    client = build_client(args)
    entry = client.entry(args.entry_id)
    enclosures = _enclosures(entry)
    if args.idx < 0 or args.idx >= len(enclosures):
        print(
            f"miniflux-cli: enclosure index out of range: {args.idx}", file=sys.stderr
        )
        return 2
    enclosure = enclosures[args.idx]
    url = enclosure.get("url")
    if not isinstance(url, str) or not url:
        print(f"miniflux-cli: enclosure has no URL: {args.idx}", file=sys.stderr)
        return 2
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else default_download_dir(args.entry_id)
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    path = download_url(url, output_dir)
    if wants_json(args):
        print_json({"path": str(path), "url": url, "idx": args.idx})
    else:
        print(path)
    return 0


def fetch_entries(
    client: MinifluxClient, args: argparse.Namespace
) -> list[dict[str, Any]]:
    category_id = resolve_category_id(client, args.category)
    query: dict[str, object] = {
        "limit": args.limit,
        "offset": args.offset,
        "order": args.order,
        "direction": args.direction,
        "starred": args.starred,
        "category_id": category_id,
        "feed_id": args.feed_id,
        "search": args.search,
        "status": args.status,
    }
    data = client.entries(query)
    entries = data.get("entries")
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    return []


def print_json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))


def print_table(rows: list[dict[str, object]], columns: list[str]) -> None:
    if not rows:
        return
    widths = {
        column: max(len(column), *(len(_display(row.get(column, ""))) for row in rows))
        for column in columns
    }
    print("  ".join(column.upper().ljust(widths[column]) for column in columns))
    print("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        print(
            "  ".join(
                _display(row.get(column, "")).ljust(widths[column])
                for column in columns
            )
        )


def wants_json(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False))


def _display(value: object) -> str:
    text = _string(value)
    return text if len(text) <= 80 else f"{text[:77]}..."


def _string(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return ""
    return str(value)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _feed_category_id(feed: dict[str, Any]) -> int | None:
    category = _dict(feed.get("category"))
    category_id = category.get("id")
    return category_id if isinstance(category_id, int) else None


def _feed_category_title(feed: dict[str, Any]) -> str:
    category = _dict(feed.get("category"))
    title = category.get("title")
    return title if isinstance(title, str) else ""


def _entry_row(entry: dict[str, Any]) -> dict[str, object]:
    feed = _dict(entry.get("feed"))
    return {
        "id": entry.get("id", ""),
        "starred": entry.get("starred", ""),
        "category": _feed_category_title(feed),
        "feed": feed.get("title", ""),
        "title": entry.get("title", ""),
    }


def _enclosures(entry: dict[str, Any]) -> list[dict[str, Any]]:
    enclosures = entry.get("enclosures")
    if isinstance(enclosures, list):
        return [enclosure for enclosure in enclosures if isinstance(enclosure, dict)]
    return []


def default_download_dir(entry_id: int) -> Path:
    return xdg_cache_home() / "miniflux-cli" / "enclosures" / str(entry_id)


def download_url(url: str, output_dir: Path) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "miniflux-cli/0.1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            filename = filename_from_response(
                url, resp.headers.get("Content-Disposition")
            )
            path = output_dir / filename
            with path.open("wb") as f:
                f.write(resp.read())
    except urllib.error.URLError as exc:
        msg = f"download failed for {url}: {exc.reason}"
        raise MinifluxError(msg) from exc
    return path


def filename_from_response(url: str, content_disposition: str | None) -> str:
    if content_disposition:
        match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", content_disposition)
        if match:
            raw = urllib.parse.unquote(match.group(1))
            return sanitize_filename(raw)
    parsed = urllib.parse.urlparse(url)
    name = Path(urllib.parse.unquote(parsed.path)).name or "enclosure"
    return sanitize_filename(name)


def sanitize_filename(value: str) -> str:
    sanitized = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value).strip()
    return sanitized or "enclosure"


def add_json_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-j", "--json", action="store_true", help="Print JSON")


def add_entry_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--starred", action="store_true", help="Only starred entries")
    parser.add_argument("--category", help="Category title or id")
    parser.add_argument("--feed-id", type=int, help="Feed id")
    parser.add_argument("--search", help="Search query")
    parser.add_argument("--status", help="Miniflux status filter")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--order", default="changed_at")
    parser.add_argument("--direction", choices=["asc", "desc"], default="desc")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read Miniflux entries as Markdown")
    parser.add_argument("-j", "--json", action="store_true", help="Print JSON")
    parser.add_argument("--config", help="Config JSON path")
    sub = parser.add_subparsers(dest="command", required=True)

    setup_parser = sub.add_parser("setup", help="Write config and check token command")
    setup_parser.add_argument("--api-url", required=True, help="Miniflux API URL")
    setup_parser.add_argument(
        "--token-command", required=True, help="Command that prints API token"
    )
    setup_parser.set_defaults(func=cmd_setup)

    list_parser = sub.add_parser("list", help="List Miniflux resources")
    list_sub = list_parser.add_subparsers(dest="resource", required=True)

    list_categories = list_sub.add_parser("categories", help="List categories")
    add_json_option(list_categories)
    list_categories.set_defaults(func=cmd_list_categories)

    list_feeds = list_sub.add_parser("feeds", help="List feeds")
    add_json_option(list_feeds)
    list_feeds.add_argument("--category", help="Category title or id")
    list_feeds.set_defaults(func=cmd_list_feeds)

    list_entries = list_sub.add_parser("entries", help="List entries")
    add_json_option(list_entries)
    add_entry_filters(list_entries)
    list_entries.set_defaults(func=cmd_list_entries)

    list_enclosures = list_sub.add_parser("enclosures", help="List entry enclosures")
    add_json_option(list_enclosures)
    list_enclosures.add_argument("entry_id", type=int)
    list_enclosures.set_defaults(func=cmd_list_enclosures)

    show_parser = sub.add_parser("show", help="Show one Miniflux resource")
    show_sub = show_parser.add_subparsers(dest="resource", required=True)

    show_entry = show_sub.add_parser("entry", help="Show an entry as Markdown")
    add_json_option(show_entry)
    show_entry.add_argument(
        "--markdown", action="store_true", help="Print Markdown (default)"
    )
    show_entry.add_argument("entry_id", type=int)
    show_entry.set_defaults(func=cmd_show_entry)

    fetch_parser = sub.add_parser("fetch", help="Fetch Miniflux content")
    fetch_sub = fetch_parser.add_subparsers(dest="resource", required=True)

    fetch_enclosure = fetch_sub.add_parser("enclosure", help="Download one enclosure")
    add_json_option(fetch_enclosure)
    fetch_enclosure.add_argument("entry_id", type=int)
    fetch_enclosure.add_argument("idx", type=int)
    fetch_enclosure.add_argument("--output-dir")
    fetch_enclosure.set_defaults(func=cmd_fetch_enclosure)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        func = args.func
        return int(func(args))
    except (ConfigError, MinifluxError, ValueError) as exc:
        print(f"miniflux-cli: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
