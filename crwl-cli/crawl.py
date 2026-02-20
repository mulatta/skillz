#!/usr/bin/env python3
"""Crawl web pages and extract markdown for LLM consumption."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path.home() / ".local" / "share" / "crwl-cli"
PROFILES_DIR = DATA_DIR / "profiles"
CACHE_DIR = DATA_DIR / "cache"

DEFAULT_EXCLUDE_TAGS = ["nav", "footer", "script", "style"]


def url_hash(url: str) -> str:
    """SHA-256 hash of URL, truncated to 16 hex chars."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


# -- fetch -----------------------------------------------------------------


async def do_fetch(args: argparse.Namespace) -> int:
    """Crawl a URL and output markdown."""
    from crawl4ai import AsyncWebCrawler
    from crawl4ai.async_configs import BrowserConfig, CacheMode, CrawlerRunConfig
    from crawl4ai.content_filter_strategy import PruningContentFilter
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    urls: list[str] = []
    if args.urls_file:
        urls = [
            line.strip()
            for line in Path(args.urls_file).read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    else:
        urls = [args.url]

    if not urls:
        print("Error: no URLs to crawl", file=sys.stderr)
        return 1

    profile_path: str | None = None
    if args.profile:
        p = PROFILES_DIR / args.profile
        if not p.exists():
            print(f"Error: profile '{args.profile}' not found", file=sys.stderr)
            print(f"  Run: crwl-cli profile create {args.profile}", file=sys.stderr)
            return 1
        profile_path = str(p)

    exclude_tags = (
        [t.strip() for t in args.exclude_tags.split(",")]
        if args.exclude_tags
        else DEFAULT_EXCLUDE_TAGS
    )

    browser_cfg = BrowserConfig(
        browser_type="chromium",
        headless=True,
        verbose=False,
        text_mode=args.text_mode,
        user_data_dir=profile_path,
        use_managed_browser=bool(profile_path),
    )

    md_gen = DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(threshold=0.45),
    )

    cache_mode = CacheMode.ENABLED if args.cache else CacheMode.BYPASS

    run_cfg = CrawlerRunConfig(
        verbose=False,
        cache_mode=cache_mode,
        markdown_generator=md_gen,
        css_selector=args.css if args.css else None,
        excluded_tags=exclude_tags,
        word_count_threshold=15,
        wait_for=f"css:{args.wait_for}" if args.wait_for else None,
        page_timeout=args.timeout,
        screenshot=args.screenshot,
    )

    results: list[dict[str, Any]] = []
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        for url in urls:
            result = await crawler.arun(url, config=run_cfg)
            entry = _build_result(url, result, args)
            results.append(entry)

            if args.cache and result.success:
                _write_cache(url, entry, result)

    return _output_results(results, args)


def _build_result(url: str, result: Any, args: argparse.Namespace) -> dict[str, Any]:
    """Build a result dict from a CrawlResult."""
    md = ""
    if result.success and result.markdown:
        if args.format == "raw":
            md = result.markdown.raw_markdown or ""
        else:
            md = result.markdown.fit_markdown or result.markdown.raw_markdown or ""

    entry: dict[str, Any] = {
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
                    "href": link["href"],
                    "text": link.get("text", ""),
                    "title": link.get("title", ""),
                }
                for link in v
            ]
            for k, v in result.links.items()
        }

    return entry


def _write_cache(url: str, entry: dict[str, Any], result: Any) -> None:
    """Write crawl result to file cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = url_hash(url)
    (CACHE_DIR / f"{h}.md").write_text(entry["markdown"])
    meta = {
        "url": url,
        "status_code": entry["status_code"],
        "crawled_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    (CACHE_DIR / f"{h}.meta.json").write_text(json.dumps(meta, indent=2))
    if result.screenshot:
        import base64

        png = base64.b64decode(result.screenshot)
        (CACHE_DIR / f"{h}.png").write_bytes(png)


def _output_results(results: list[dict[str, Any]], args: argparse.Namespace) -> int:
    """Output results in the requested format."""
    failed = 0
    for entry in results:
        if not entry["success"]:
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
            print(entry["markdown"])

    return 1 if failed == len(results) else 0


# -- profile ---------------------------------------------------------------


async def do_profile_create(args: argparse.Namespace) -> int:
    """Create a browser profile interactively."""
    from crawl4ai import BrowserProfiler

    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    dest = PROFILES_DIR / args.name
    if dest.exists():
        print(f"Error: profile '{args.name}' already exists", file=sys.stderr)
        return 1

    profiler = BrowserProfiler()
    profile_path: str = await profiler.create_profile(profile_name=args.name)

    # Move from default crawl4ai location to our XDG path
    src = Path(profile_path)
    if src != dest and src.exists():
        shutil.move(str(src), str(dest))
        print(f"Profile '{args.name}' saved to {dest}")
    else:
        print(f"Profile '{args.name}' at {profile_path}")

    return 0


def do_profile_list(_args: argparse.Namespace) -> int:
    """List available browser profiles."""
    if not PROFILES_DIR.exists():
        print("No profiles found.")
        return 0

    profiles = sorted(PROFILES_DIR.iterdir())
    if not profiles:
        print("No profiles found.")
        return 0

    for p in profiles:
        if p.is_dir():
            stat = p.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            print(f"  {p.name:20s}  {mtime:%Y-%m-%d %H:%M}")
    return 0


def do_profile_delete(args: argparse.Namespace) -> int:
    """Delete a browser profile."""
    p = PROFILES_DIR / args.name
    if not p.exists():
        print(f"Error: profile '{args.name}' not found", file=sys.stderr)
        return 1
    shutil.rmtree(p)
    print(f"Deleted profile '{args.name}'")
    return 0


async def do_profile_check(args: argparse.Namespace) -> int:
    """Test a profile by crawling a URL and showing a preview."""
    from crawl4ai import AsyncWebCrawler
    from crawl4ai.async_configs import BrowserConfig, CacheMode, CrawlerRunConfig

    p = PROFILES_DIR / args.name
    if not p.exists():
        print(f"Error: profile '{args.name}' not found", file=sys.stderr)
        return 1

    browser_cfg = BrowserConfig(
        browser_type="chromium",
        headless=True,
        verbose=False,
        user_data_dir=str(p),
        use_managed_browser=True,
    )
    run_cfg = CrawlerRunConfig(verbose=False, cache_mode=CacheMode.BYPASS)

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(args.url, config=run_cfg)

    if not result.success:
        print(f"Error: {result.error_message}", file=sys.stderr)
        return 1

    md = ""
    if result.markdown:
        md = result.markdown.fit_markdown or result.markdown.raw_markdown or ""

    preview = md[:500]
    print(f"Status: {result.status_code}")
    print(f"Preview ({len(md)} chars total):")
    print(preview)
    if len(md) > 500:
        print("...")
    return 0


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

    now = datetime.now(tz=timezone.utc)
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
        description="Crawl web pages and extract markdown for LLM consumption",
    )
    sub = parser.add_subparsers(dest="command")

    # -- fetch
    fetch = sub.add_parser("fetch", help="Crawl URL(s) and extract markdown")
    fetch.add_argument("url", nargs="?", help="URL to crawl")
    fetch.add_argument("--urls-file", help="File with URLs (one per line)")
    fetch.add_argument("--profile", help="Browser profile name for auth")
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
    fetch.add_argument("--cache", action="store_true", help="Enable caching")
    fetch.add_argument(
        "--timeout", type=int, default=30000, help="Page timeout in ms (default: 30000)"
    )
    fetch.add_argument("--screenshot", action="store_true", help="Capture screenshot")
    fetch.add_argument(
        "--text-mode", action="store_true", help="Disable images for speed"
    )

    # -- profile
    profile = sub.add_parser("profile", help="Manage browser profiles")
    profile_sub = profile.add_subparsers(dest="profile_command")

    pc = profile_sub.add_parser("create", help="Create a browser profile")
    pc.add_argument("name", help="Profile name")

    profile_sub.add_parser("list", help="List profiles")

    pd = profile_sub.add_parser("delete", help="Delete a profile")
    pd.add_argument("name", help="Profile name")

    pck = profile_sub.add_parser("check", help="Test profile with a URL")
    pck.add_argument("name", help="Profile name")
    pck.add_argument("url", help="URL to test")

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

    if args.command == "profile":
        if args.profile_command == "create":
            return asyncio.run(do_profile_create(args))
        if args.profile_command == "list":
            return do_profile_list(args)
        if args.profile_command == "delete":
            return do_profile_delete(args)
        if args.profile_command == "check":
            return asyncio.run(do_profile_check(args))
        parser.error("profile subcommand required")

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
