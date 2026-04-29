#!/usr/bin/env python3
"""Crawl public web pages and extract markdown for LLM consumption."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, Self, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

DATA_DIR = Path.home() / ".local" / "share" / "crwl-cli"
CACHE_DIR = DATA_DIR / "cache"
SCREENSHOT_DIR = DATA_DIR / "screenshots"

DEFAULT_EXCLUDE_TAGS = ["nav", "footer", "script", "style"]


class MarkdownResult(Protocol):
    raw_markdown: str | None
    fit_markdown: str | None


class CrawlResult(Protocol):
    success: bool
    markdown: MarkdownResult | None
    status_code: int | None
    error_message: str | None
    links: Mapping[str, Sequence[Mapping[str, object]]] | None
    screenshot: str | None


class WebCrawler(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    async def arun(self, url: str, config: object) -> CrawlResult: ...


def url_hash(url: str) -> str:
    """SHA-256 hash of URL, truncated to 16 hex chars."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def parse_viewport(value: str) -> tuple[int, int]:
    """Parse WIDTHxHEIGHT viewport value."""
    try:
        width_raw, height_raw = value.lower().split("x", 1)
        width = int(width_raw)
        height = int(height_raw)
    except ValueError as exc:
        msg = "viewport must be WIDTHxHEIGHT, e.g. 1920x1080"
        raise argparse.ArgumentTypeError(msg) from exc

    if width <= 0 or height <= 0:
        msg = "viewport dimensions must be positive integers"
        raise argparse.ArgumentTypeError(msg)
    return width, height


# -- fetch -----------------------------------------------------------------


def _read_urls(args: argparse.Namespace) -> list[str]:
    """Read crawl URL(s) from arguments."""
    if args.urls_file:
        return [
            line.strip()
            for line in Path(args.urls_file).read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    return [args.url]


def _build_browser_config(args: argparse.Namespace) -> object:
    """Build Crawl4AI BrowserConfig from safe headless CLI flags."""
    async_configs = importlib.import_module("crawl4ai.async_configs")
    browser_config = cast("Callable[..., object]", async_configs.BrowserConfig)

    kwargs: dict[str, object] = {
        "browser_type": "chromium",
        "headless": True,
        "verbose": False,
        "text_mode": args.text_mode,
        "enable_stealth": args.stealth,
        "ignore_https_errors": args.ignore_https_errors,
    }

    if args.user_agent_mode == "random":
        kwargs["user_agent_mode"] = "random"

    if args.viewport:
        width, height = args.viewport
        kwargs["viewport_width"] = width
        kwargs["viewport_height"] = height

    try:
        return browser_config(**kwargs)
    except TypeError as exc:
        msg = f"Error: unsupported Crawl4AI browser option: {exc}"
        raise RuntimeError(msg) from exc


def _build_run_config(args: argparse.Namespace) -> object:
    """Build Crawl4AI CrawlerRunConfig from safe extraction flags."""
    async_configs = importlib.import_module("crawl4ai.async_configs")
    content_filter_strategy = importlib.import_module(
        "crawl4ai.content_filter_strategy"
    )
    markdown_generation_strategy = importlib.import_module(
        "crawl4ai.markdown_generation_strategy"
    )
    cache_mode_cls = async_configs.CacheMode
    crawler_run_config = cast("Callable[..., object]", async_configs.CrawlerRunConfig)
    pruning_content_filter = cast(
        "Callable[..., object]", content_filter_strategy.PruningContentFilter
    )
    default_markdown_generator = cast(
        "Callable[..., object]",
        markdown_generation_strategy.DefaultMarkdownGenerator,
    )

    exclude_tags = (
        [t.strip() for t in args.exclude_tags.split(",")]
        if args.exclude_tags
        else DEFAULT_EXCLUDE_TAGS
    )

    md_gen = default_markdown_generator(
        content_filter=pruning_content_filter(threshold=0.45),
    )

    cache_mode = cache_mode_cls.ENABLED if args.cache else cache_mode_cls.BYPASS

    kwargs: dict[str, object] = {
        "verbose": False,
        "cache_mode": cache_mode,
        "markdown_generator": md_gen,
        "css_selector": args.css or None,
        "excluded_tags": exclude_tags,
        "word_count_threshold": 15,
        "wait_for": f"css:{args.wait_for}" if args.wait_for else None,
        "page_timeout": args.timeout,
        "screenshot": args.screenshot,
        "scan_full_page": args.scan_full_page,
    }

    try:
        return crawler_run_config(**kwargs)
    except TypeError as exc:
        msg = f"Error: unsupported Crawl4AI crawler option: {exc}"
        raise RuntimeError(msg) from exc


async def do_fetch(args: argparse.Namespace) -> int:
    """Crawl URL(s) and output markdown or JSON."""
    urls = _read_urls(args)
    if not urls:
        print("Error: no URLs to crawl", file=sys.stderr)
        return 1

    try:
        browser_cfg = _build_browser_config(args)
        run_cfg = _build_run_config(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    crawl4ai = importlib.import_module("crawl4ai")
    async_web_crawler = cast("Callable[..., WebCrawler]", crawl4ai.AsyncWebCrawler)

    results: list[dict[str, object]] = []
    async with async_web_crawler(config=browser_cfg) as crawler:
        for url in urls:
            result = await crawler.arun(url, config=run_cfg)
            entry = _build_result(url, result, args)
            results.append(entry)

            if args.cache and result.success:
                _write_cache(url, entry, result)
            elif args.screenshot and result.success and result.screenshot:
                entry["screenshot_path"] = _write_screenshot(url, result.screenshot)

    return _output_results(results, args)


def _build_result(
    url: str, result: CrawlResult, args: argparse.Namespace
) -> dict[str, object]:
    """Build a result dict from a CrawlResult."""
    md = ""
    if result.success and result.markdown:
        if args.format == "raw":
            md = result.markdown.raw_markdown or ""
        else:
            md = result.markdown.fit_markdown or result.markdown.raw_markdown or ""

    entry: dict[str, object] = {
        "url": url,
        "success": result.success,
        "status_code": result.status_code,
        "markdown": md,
        "error": result.error_message if not result.success else None,
    }

    if args.format == "json" and result.success and result.links:
        entry["links"] = {
            k: [
                {
                    "href": str(link["href"]),
                    "text": link.get("text", ""),
                    "title": link.get("title", ""),
                }
                for link in v
            ]
            for k, v in result.links.items()
        }

    return entry


def _write_screenshot(url: str, screenshot: str) -> str:
    """Write a base64 PNG screenshot and return its path."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{url_hash(url)}.png"
    path.write_bytes(base64.b64decode(screenshot))
    return str(path)


def _write_cache(url: str, entry: dict[str, object], result: CrawlResult) -> None:
    """Write crawl result to file cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = url_hash(url)
    (CACHE_DIR / f"{h}.md").write_text(str(entry["markdown"]))
    meta = {
        "url": url,
        "status_code": entry["status_code"],
        "crawled_at": datetime.now(tz=UTC).isoformat(),
    }
    if result.screenshot:
        meta["screenshot_path"] = str(CACHE_DIR / f"{h}.png")
    (CACHE_DIR / f"{h}.meta.json").write_text(json.dumps(meta, indent=2))
    if result.screenshot:
        (CACHE_DIR / f"{h}.png").write_bytes(base64.b64decode(result.screenshot))
        entry["screenshot_path"] = meta["screenshot_path"]


def _output_results(results: list[dict[str, object]], args: argparse.Namespace) -> int:
    """Output results in the requested format."""
    failed = 0
    for entry in results:
        if not bool(entry["success"]):
            print(
                f"Error: {entry['url']}: {entry['error']}",
                file=sys.stderr,
            )
            failed += 1
            continue

        if args.format == "json":
            print(json.dumps(entry, ensure_ascii=False))
        else:
            # md or raw
            if len(results) > 1:
                print(f"--- {entry['url']} ---")
            print(str(entry["markdown"]))
            if entry.get("screenshot_path"):
                print(f"\nScreenshot: {entry['screenshot_path']}", file=sys.stderr)

    return 1 if failed == len(results) else 0


# -- cache ------------------------------------------------------------------


def do_cache_list(_args: argparse.Namespace) -> int:
    """List cached crawl results."""
    if not CACHE_DIR.exists():
        print("Cache is empty.")
        return 0

    metas = sorted(CACHE_DIR.glob("*.meta.json"))
    if not metas:
        print("Cache is empty.")
        return 0

    for meta_path in metas:
        meta = json.loads(meta_path.read_text())
        md_path = meta_path.with_suffix("").with_suffix(".md")
        size = md_path.stat().st_size if md_path.exists() else 0
        print(
            f"  {meta.get('crawled_at', '?'):25s}  {size:>8d}B  {meta.get('url', '?')}"
        )
    return 0


def do_cache_clear(args: argparse.Namespace) -> int:
    """Clear cached crawl results."""
    if not CACHE_DIR.exists():
        print("Cache is already empty.")
        return 0

    now = datetime.now(tz=UTC)
    removed = 0

    for meta_path in list(CACHE_DIR.glob("*.meta.json")):
        meta = json.loads(meta_path.read_text())
        crawled_at = datetime.fromisoformat(meta["crawled_at"])
        age_days = (now - crawled_at).days

        if args.older_than is not None and age_days < args.older_than:
            continue

        stem = meta_path.stem.removesuffix(".meta")
        for suffix in (".md", ".meta.json", ".png"):
            f = CACHE_DIR / f"{stem}{suffix}"
            if f.exists():
                f.unlink()
        removed += 1

    print(f"Removed {removed} cached entries.")
    return 0


# -- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="crwl-cli",
        description="Headless public web crawler for LLM-readable markdown",
    )
    sub = parser.add_subparsers(dest="command")

    # -- fetch
    fetch = sub.add_parser("fetch", help="Crawl public URL(s) and extract markdown")
    fetch.add_argument("url", nargs="?", help="Public URL to crawl")
    fetch.add_argument("--urls-file", help="File with URLs (one per line)")
    fetch.add_argument(
        "--format",
        choices=["md", "json", "raw"],
        default="md",
        help="Output format (default: md)",
    )
    fetch.add_argument("--css", help="CSS selector to limit scope")
    fetch.add_argument(
        "--exclude-tags",
        help="Comma-separated tags to exclude (default: nav,footer,script,style)",
    )
    fetch.add_argument("--wait-for", help="CSS selector to wait for before extraction")
    fetch.add_argument(
        "--scan-full-page",
        action="store_true",
        help="Scroll through full page before extraction",
    )
    fetch.add_argument("--cache", action="store_true", help="Enable caching")
    fetch.add_argument(
        "--timeout", type=int, default=30000, help="Page timeout in ms (default: 30000)"
    )
    fetch.add_argument("--screenshot", action="store_true", help="Capture screenshot")
    fetch.add_argument(
        "--text-mode", action="store_true", help="Disable images for speed"
    )
    fetch.add_argument(
        "--stealth",
        action="store_true",
        help="Enable Crawl4AI/Playwright stealth mode",
    )
    fetch.add_argument(
        "--user-agent-mode",
        choices=["default", "random"],
        default="default",
        help="User agent mode (default: default)",
    )
    fetch.add_argument(
        "--viewport",
        type=parse_viewport,
        metavar="WIDTHxHEIGHT",
        help="Browser viewport, e.g. 1920x1080",
    )
    fetch.add_argument(
        "--ignore-https-errors",
        action="store_true",
        help="Ignore invalid TLS certificates",
    )

    # -- cache
    cache = sub.add_parser("cache", help="Manage crawl cache")
    cache_sub = cache.add_subparsers(dest="cache_command")

    cache_sub.add_parser("list", help="List cached results")

    cc = cache_sub.add_parser("clear", help="Clear cache")
    cc.add_argument(
        "--older-than",
        type=int,
        help="Only remove entries older than N days",
    )

    return parser


def main() -> int:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "fetch":
        if not args.url and not args.urls_file:
            parser.error("provide a URL or --urls-file")
        return asyncio.run(do_fetch(args))

    if args.command == "cache":
        if args.cache_command == "list":
            return do_cache_list(args)
        if args.cache_command == "clear":
            return do_cache_clear(args)
        parser.error("cache subcommand required")

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
