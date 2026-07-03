"""Command-line entry point.

``get`` resolves native IDs / DOI metadata, tries legal OA PDFs, then falls
back to institutional PDF / full text through the browser. ``render`` / ``grab``
are low-level browser primitives; ``setup`` writes config. The browser engine is
imported lazily so ``--help`` and argument parsing do not require patchright.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from paperfetch_cli import __version__
from paperfetch_cli.config import (
    browser_config_from_args,
    config_path,
    load_file_config,
    unpaywall_email_from_args,
)
from paperfetch_cli.errors import (
    EXIT_OK,
    EXIT_UNRESOLVED,
    EXIT_USAGE,
    CLIError,
)
from paperfetch_cli.resolve import (
    PaperMeta,
    arxiv_paper_meta,
    cellpress_article_url,
    citation_pdf_url,
    download_file,
    parse_identifier,
    pdf_candidates,
    publisher_pdf_url,
    resolve_arxiv_metadata,
    resolve_europepmc,
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
    identifier = parse_identifier(target)
    if identifier is None:
        msg = "input is not a DOI, URL, arXiv ID, PMID, or PMCID"
        raise CLIError(msg, EXIT_USAGE)
    if identifier.kind == "arxiv":
        meta = arxiv_paper_meta(identifier.value)
        with contextlib.suppress(CLIError):
            meta = resolve_arxiv_metadata(identifier.value)
        return _emit_get(args, meta, meta.landing_url)
    if identifier.kind == "url":
        meta = PaperMeta(doi="", landing_url=identifier.value)
        return _emit_get(args, meta, identifier.value)

    doi = identifier.value if identifier.kind == "doi" else None
    pmcid = identifier.value if identifier.kind == "pmcid" else None
    pmid = identifier.value if identifier.kind == "pmid" else None
    meta = PaperMeta(doi=doi or "", pmid=pmid or "", pmcid=pmcid or "")
    if doi is not None:
        with contextlib.suppress(CLIError):
            meta = resolve_metadata(doi, unpaywall_email_from_args(args))
    with contextlib.suppress(CLIError):
        meta = _merge_meta(
            meta,
            resolve_europepmc(doi=doi, pmid=pmid, pmcid=pmcid),
        )
    # Prefer the doi.org resolver over OpenAlex's landing_page_url: it redirects
    # to the canonical publisher article page (cell.com, science.org, ...) where
    # citation_pdf_url / the per-publisher pattern apply, whereas OpenAlex may
    # point at an aggregator.
    landing = (
        (target if identifier.is_url else None)
        or (f"https://doi.org/{doi}" if doi else None)
        or meta.landing_url
    )
    return _emit_get(args, meta, landing)


def _merge_meta(base: PaperMeta, extra: PaperMeta) -> PaperMeta:
    use_extra_pdf = extra.oa_pdf_url is not None
    return PaperMeta(
        doi=base.doi or extra.doi,
        title=base.title or extra.title,
        authors=base.authors or extra.authors,
        journal=base.journal or extra.journal,
        year=base.year or extra.year,
        oa_pdf_url=extra.oa_pdf_url or base.oa_pdf_url,
        landing_url=base.landing_url or extra.landing_url,
        pmid=base.pmid or extra.pmid,
        pmcid=base.pmcid or extra.pmcid,
        arxiv_id=base.arxiv_id or extra.arxiv_id,
        oa_pdf_source=extra.oa_pdf_source if use_extra_pdf else base.oa_pdf_source,
        oa_landing_url=extra.oa_landing_url or base.oa_landing_url,
    )


def _slug(meta: PaperMeta) -> str:
    if meta.arxiv_id:
        return "arxiv_" + meta.arxiv_id.replace("/", "_")
    if meta.doi:
        return meta.doi.replace("/", "_")
    return meta.pmcid or (f"PMID{meta.pmid}" if meta.pmid else "paper")


def _manifest(meta: PaperMeta) -> dict[str, object]:
    manifest: dict[str, object] = {
        "doi": meta.doi,
        "title": meta.title,
        "authors": list(meta.authors),
        "journal": meta.journal,
        "year": meta.year,
        "landing_url": meta.landing_url,
    }
    if meta.pmid:
        manifest["pmid"] = meta.pmid
    if meta.pmcid:
        manifest["pmcid"] = meta.pmcid
    if meta.arxiv_id:
        manifest["arxiv"] = meta.arxiv_id
    if meta.oa_pdf_url:
        manifest["pdf"] = {"url": meta.oa_pdf_url, "via": meta.oa_pdf_source}
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
        except CLIError as exc:
            # OA direct download is a best-effort fast path. If a Europe PMC /
            # PMC URL failed as HTML, keep that legal landing in the browser path
            # instead of falling back to doi.org and losing the cleaner source.
            if meta.oa_pdf_source in {"europepmc", "pmc_oa"}:
                warnings.append(str(exc))
                landing = meta.oa_landing_url or meta.landing_url or landing
        else:
            manifest["pdf"] = {
                "url": meta.oa_pdf_url,
                "via": meta.oa_pdf_source,
                "path": str(dest),
            }
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


def _print_optional_line(manifest: dict[str, object], key: str, stream: TextIO) -> None:
    value = manifest.get(key)
    if value:
        print(f"  {key}: {value}", file=stream)


def _print_human(manifest: dict[str, object], *, to_stderr: bool = False) -> None:
    stream = sys.stderr if to_stderr else sys.stdout
    print(manifest.get("title") or "(no title)", file=stream)
    print(f"  doi: {manifest.get('doi')}", file=stream)
    _print_optional_line(manifest, "pmid", stream)
    _print_optional_line(manifest, "pmcid", stream)
    _print_optional_line(manifest, "arxiv", stream)
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
    if args.unpaywall_email:
        data["unpaywall_email"] = args.unpaywall_email
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"wrote {path}")
    return EXIT_OK


def _build_get(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "get", help="resolve a paper's artifacts from a URL, DOI, or native ID"
    )
    parser.add_argument("target", metavar="URL|DOI|ID")
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
    parser.add_argument(
        "--unpaywall-email",
        metavar="EMAIL",
        help=(
            "contact email for direct Unpaywall OA fallback "
            "(or PAPERFETCH_UNPAYWALL_EMAIL / config)"
        ),
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
        "setup", help="write configuration (profile dir, chromium path, OA email)"
    )
    parser.add_argument("--profile-dir", metavar="DIR")
    parser.add_argument("--chromium", metavar="PATH")
    parser.add_argument(
        "--unpaywall-email",
        metavar="EMAIL",
        help="contact email saved for direct Unpaywall OA fallback",
    )
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
