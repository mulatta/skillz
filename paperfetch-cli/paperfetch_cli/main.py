"""Command-line entry point.

``get`` resolves a paper (metadata via OpenAlex, open-access PDF, then the
institutional PDF / full text through the browser); ``render`` / ``grab`` are
the low-level browser primitives; ``setup`` writes config. The browser engine is
imported lazily so ``--help`` and argument parsing do not require patchright.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from paperfetch_cli import __version__
from paperfetch_cli.config import (
    browser_config_from_args,
    config_path,
    load_file_config,
)
from paperfetch_cli.errors import (
    EXIT_OK,
    EXIT_UNRESOLVED,
    EXIT_USAGE,
    CLIError,
)
from paperfetch_cli.resolve import (
    PaperMeta,
    cellpress_article_url,
    citation_pdf_url,
    download_file,
    normalize_doi,
    pdf_candidates,
    publisher_pdf_url,
    resolve_metadata,
    sciencedirect_pdf_url,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from paperfetch_cli.browser import Browser, PageResult


def _add_browser_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("browser / auth")
    group.add_argument(
        "--cookies", metavar="FILE", help="netscape cookie jar to inject"
    )
    group.add_argument(
        "--profile", metavar="DIR", help="persistent browser profile directory"
    )
    group.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="K:V",
        help="extra request header (repeatable)",
    )
    group.add_argument(
        "--headful",
        dest="headful",
        action="store_true",
        default=True,
        help="run a headful browser (default; needed to clear Cloudflare)",
    )
    group.add_argument(
        "--headless",
        dest="headful",
        action="store_false",
        help="run headless (fails on Cloudflare-protected sites)",
    )
    group.add_argument("--executable", metavar="PATH", help="chromium executable path")
    group.add_argument("--timeout", type=int, default=60, metavar="SECONDS")


def cmd_get(args: argparse.Namespace) -> int:
    target = args.target.strip()
    is_url = target.lower().startswith(("http://", "https://"))
    doi = normalize_doi(target)
    if doi is None and not is_url:
        msg = "input is neither a DOI nor an http(s) URL"
        raise CLIError(msg, EXIT_USAGE)
    meta = PaperMeta(doi=doi or "")
    if doi is not None:
        with contextlib.suppress(CLIError):
            meta = resolve_metadata(doi)
    # Prefer the doi.org resolver over OpenAlex's landing_page_url: it redirects
    # to the canonical publisher article page (cell.com, science.org, ...) where
    # citation_pdf_url / the per-publisher pattern apply, whereas OpenAlex may
    # point at an aggregator.
    landing = (
        (target if is_url else None)
        or (f"https://doi.org/{doi}" if doi else None)
        or meta.landing_url
    )
    return _emit_get(args, meta, landing)


def _slug(meta: PaperMeta) -> str:
    return meta.doi.replace("/", "_") if meta.doi else "paper"


def _manifest(meta: PaperMeta) -> dict[str, object]:
    manifest: dict[str, object] = {
        "doi": meta.doi,
        "title": meta.title,
        "authors": list(meta.authors),
        "journal": meta.journal,
        "year": meta.year,
        "landing_url": meta.landing_url,
    }
    if meta.oa_pdf_url:
        manifest["pdf"] = {"url": meta.oa_pdf_url, "via": "oa"}
    return manifest


def _emit_get(args: argparse.Namespace, meta: PaperMeta, landing: str | None) -> int:
    manifest = _manifest(meta)
    warnings: list[str] = []
    rc = EXIT_OK
    # Open-access PDF first - no browser, no publisher hit.
    pdf_done = False
    if args.pdf and meta.oa_pdf_url and not args.pdf_url:
        dest = Path(args.out) / (_slug(meta) + ".pdf")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            download_file(meta.oa_pdf_url, dest)
        except CLIError:
            # OA direct download is a best-effort fast path; on failure fall
            # through to the browser fetch instead of surfacing it as a warning.
            pass
        else:
            manifest["pdf"] = {"url": meta.oa_pdf_url, "via": "oa", "path": str(dest)}
            pdf_done = True
    md_text: str | None = None
    if args.md or args.html or (args.pdf and not pdf_done):
        if landing is None:
            warnings.append("no landing URL to open in the browser")
            rc = EXIT_UNRESOLVED
        else:
            md_text, browser_rc = _browser_get(args, meta, manifest, landing, warnings)
            rc = browser_rc or rc
    if warnings:
        manifest["warnings"] = warnings
    if md_text is not None:
        print(md_text)
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False))
    else:
        _print_human(manifest, to_stderr=md_text is not None)
    return rc


def _browser_get(
    args: argparse.Namespace,
    meta: PaperMeta,
    manifest: dict[str, object],
    landing: str,
    warnings: list[str],
) -> tuple[str | None, int]:
    from paperfetch_cli.browser import Browser  # noqa: PLC0415

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_text: str | None = None
    rc = EXIT_OK
    with Browser(browser_config_from_args(args)) as browser:
        page = browser.render(landing)
        # A Cell DOI lands on Elsevier; the article is also on cell.com (same
        # PII) where the PDF is reachable - re-render there.
        cell_url = cellpress_article_url(page.url)
        if cell_url is not None and cell_url != page.url:
            page = browser.render(cell_url)
        if page.challenged:
            warnings.append("Cloudflare challenge did not clear")
        if args.html:
            dest = out_dir / (_slug(meta) + ".html")
            dest.write_text(page.html, encoding="utf-8")
            manifest["html_path"] = str(dest)
        if args.md:
            md_text = _render_content("md", page.html)
            manifest["fulltext"] = {"chars": len(md_text)}
        if args.pdf:
            rc = _browser_pdf(args, meta, manifest, browser, page, warnings, out_dir)
    return md_text, rc


def _browser_pdf(  # noqa: PLR0913
    args: argparse.Namespace,
    meta: PaperMeta,
    manifest: dict[str, object],
    browser: Browser,
    page: PageResult,
    warnings: list[str],
    out_dir: Path,
) -> int:
    cited = citation_pdf_url(page.html)
    sd = sciencedirect_pdf_url(page.html, page.url)
    pdf_url = args.pdf_url or cited or sd or publisher_pdf_url(page.url)
    if pdf_url is None:
        warnings.append("no PDF URL found on the page")
        manifest["candidates"] = {"pdf_links": pdf_candidates(page.links)}
        return EXIT_UNRESOLVED
    if args.pdf_url:
        via = "explicit"
    elif cited:
        via = "citation_pdf_url"
    elif sd:
        via = "sciencedirect"
    else:
        via = "adapter"
    try:
        result = browser.fetch_pdf(pdf_url, context_url=page.url)
    except CLIError as exc:
        warnings.append(str(exc))
        manifest["candidates"] = {"pdf_links": pdf_candidates(page.links)}
        return EXIT_UNRESOLVED
    if result.data[:5] != b"%PDF-":
        warnings.append(f"fetched {pdf_url} but it was not a PDF")
        manifest["candidates"] = {"pdf_links": pdf_candidates(page.links)}
        return EXIT_UNRESOLVED
    dest = out_dir / (_slug(meta) + ".pdf")
    dest.write_bytes(result.data)
    manifest["pdf"] = {"url": pdf_url, "via": via, "path": str(dest)}
    return EXIT_OK


def _print_human(manifest: dict[str, object], *, to_stderr: bool = False) -> None:
    stream = sys.stderr if to_stderr else sys.stdout
    print(manifest.get("title") or "(no title)", file=stream)
    print(f"  doi: {manifest.get('doi')}", file=stream)
    if manifest.get("journal"):
        print(
            f"  journal: {manifest.get('journal')} ({manifest.get('year')})",
            file=stream,
        )
    pdf = manifest.get("pdf")
    if isinstance(pdf, dict):
        print(
            f"  pdf ({pdf.get('via')}): {pdf.get('path') or pdf.get('url')}",
            file=stream,
        )
    fulltext = manifest.get("fulltext")
    if isinstance(fulltext, dict):
        print(f"  fulltext: {fulltext.get('chars')} chars", file=stream)
    if manifest.get("html_path"):
        print(f"  html: {manifest.get('html_path')}", file=stream)
    candidates = manifest.get("candidates")
    if isinstance(candidates, dict):
        links = candidates.get("pdf_links")
        if isinstance(links, list) and links:
            print(f"  candidates: {len(links)} pdf link(s)", file=stream)
    warns = manifest.get("warnings")
    if isinstance(warns, list):
        for warning in warns:
            print(f"  warning: {warning}", file=stream)


def _require_url(url: str) -> None:
    if not url.lower().startswith(("http://", "https://")):
        msg = f"expected an http(s) URL, got {url!r} - for a DOI use `get`"
        raise CLIError(msg, EXIT_USAGE)


def cmd_render(args: argparse.Namespace) -> int:
    from paperfetch_cli.browser import Browser  # noqa: PLC0415

    _require_url(args.url)
    cfg = browser_config_from_args(args)
    with Browser(cfg) as browser:
        result = browser.render(args.url, wait_for=args.wait_for, wait_ms=args.wait_ms)
    return _emit_render(args, result)


def _render_content(fmt: str, html: str) -> str:
    if fmt == "html":
        return html
    from markdownify import markdownify  # noqa: PLC0415

    if fmt == "text":
        return str(markdownify(html, strip=["a", "img"]))
    return str(markdownify(html))


def _emit_render(args: argparse.Namespace, result: PageResult) -> int:
    if args.json:
        payload: dict[str, object] = {
            "url": result.url,
            "status": result.status,
            "title": result.title,
            "challenged": result.challenged,
            "content": _render_content(args.format, result.html),
        }
        if args.links:
            payload["links"] = result.links
        print(json.dumps(payload, ensure_ascii=False))
    elif args.links:
        for link in result.links:
            print(link)
    else:
        print(_render_content(args.format, result.html))
    return EXIT_UNRESOLVED if result.challenged else EXIT_OK


def cmd_grab(args: argparse.Namespace) -> int:
    from paperfetch_cli.browser import Browser  # noqa: PLC0415

    _require_url(args.url)
    cfg = browser_config_from_args(args)
    with Browser(cfg) as browser:
        result = browser.fetch_bytes(
            args.url, expect=args.expect, context_url=args.context
        )
    Path(args.out).write_bytes(result.data)
    print(args.out)
    return EXIT_OK


def cmd_setup(args: argparse.Namespace) -> int:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_file_config()
    if args.profile_dir:
        data["profile_dir"] = args.profile_dir
    if args.chromium:
        data["chromium"] = args.chromium
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"wrote {path}")
    return EXIT_OK


def _build_get(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("get", help="resolve a paper's artifacts from a URL or DOI")
    parser.add_argument("target", metavar="URL|DOI")
    parser.add_argument(
        "--md",
        action="store_true",
        help="render the article page and emit full-text markdown to stdout",
    )
    parser.add_argument(
        "--html", action="store_true", help="save the rendered article HTML to --out"
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="download the PDF to --out (open access, else institutional via browser)",
    )
    parser.add_argument(
        "--pdf-url",
        metavar="URL",
        help="explicit PDF URL (escape hatch; skips discovery)",
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=".",
        help="output directory for downloaded files",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the manifest as JSON to stdout"
    )
    _add_browser_options(parser)
    parser.set_defaults(handler=cmd_get)


def _build_render(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "render", help="headful render of a URL (low-level primitive)"
    )
    parser.add_argument("url", metavar="URL")
    parser.add_argument("--format", choices=("md", "html", "text"), default="md")
    parser.add_argument("--links", action="store_true", help="emit discovered links")
    parser.add_argument(
        "--wait-for", metavar="SEL", help="selector to wait for before extracting"
    )
    parser.add_argument(
        "--wait-ms", type=int, metavar="N", help="extra wait after load"
    )
    parser.add_argument("--json", action="store_true")
    _add_browser_options(parser)
    parser.set_defaults(handler=cmd_render)


def _build_grab(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "grab", help="headful authenticated download of a URL (low-level primitive)"
    )
    parser.add_argument("url", metavar="URL")
    parser.add_argument("--out", metavar="FILE", required=True)
    parser.add_argument(
        "--expect", metavar="MIME", help="fail if the response is not this content type"
    )
    parser.add_argument(
        "--from",
        dest="context",
        metavar="URL",
        help="page to load first for Cloudflare clearance (e.g. the article page)",
    )
    _add_browser_options(parser)
    parser.set_defaults(handler=cmd_grab)


def _build_setup(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "setup", help="write configuration (profile dir, chromium path)"
    )
    parser.add_argument("--profile-dir", metavar="DIR")
    parser.add_argument("--chromium", metavar="PATH")
    parser.set_defaults(handler=cmd_setup)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paperfetch-cli",
        description="Fetch an academic paper's full text and PDF on demand.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.set_defaults(handler=None)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    _build_get(sub)
    _build_render(sub)
    _build_grab(sub)
    _build_setup(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.handler is None:
        parser.print_help()
        return EXIT_USAGE
    try:
        return int(args.handler(args))
    except CLIError as exc:
        print(f"paperfetch-cli: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
