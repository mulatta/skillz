"""Paper metadata + open-access resolution via keyless JSON APIs.

OpenAlex returns both bibliographic metadata and the best open-access PDF
location from a single DOI lookup, and it is not bot-walled, so this path is
safe to run freely (no publisher scraping). The browser is only needed later for
paywalled full text / PDF.
"""

from __future__ import annotations

import json
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

from paperfetch_cli.errors import EXIT_FETCH, EXIT_UNRESOLVED, CLIError

if TYPE_CHECKING:
    from pathlib import Path

_DOI_RE = re.compile(r"10\.\d{4,9}/\S+")
_OPENALEX = "https://api.openalex.org/works/doi:"
_TIMEOUT = 20
_UA = "paperfetch-cli (https://github.com/mulatta/skillz)"


@dataclass
class PaperMeta:
    doi: str
    title: str = ""
    authors: tuple[str, ...] = ()
    journal: str = ""
    year: int | None = None
    oa_pdf_url: str | None = None
    landing_url: str | None = None


def normalize_doi(value: str) -> str | None:
    match = _DOI_RE.search(value.strip())
    if match is None:
        return None
    return match.group(0).rstrip(").,;>").lower()


def _get_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(  # noqa: S310 - https URL built from constants
        url,
        headers={"User-Agent": _UA, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310
            payload: object = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        msg = f"metadata lookup failed: {exc}"
        raise CLIError(msg, EXIT_UNRESOLVED) from exc
    if not isinstance(payload, dict):
        msg = "unexpected metadata response"
        raise CLIError(msg, EXIT_UNRESOLVED)
    return payload


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _authors(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names = [
        _str(_dict(_dict(item).get("author")).get("display_name")) for item in value
    ]
    return tuple(name for name in names if name)


def parse_openalex(data: dict[str, object], doi: str) -> PaperMeta:
    best_oa = _dict(data.get("best_oa_location"))
    primary = _dict(data.get("primary_location"))
    year = data.get("publication_year")
    return PaperMeta(
        doi=doi,
        title=_str(data.get("title")) or _str(data.get("display_name")),
        authors=_authors(data.get("authorships")),
        journal=_str(_dict(primary.get("source")).get("display_name")),
        year=year if isinstance(year, int) else None,
        oa_pdf_url=_str(best_oa.get("pdf_url")) or None,
        landing_url=_str(primary.get("landing_page_url")) or None,
    )


def resolve_metadata(doi: str) -> PaperMeta:
    data = _get_json(_OPENALEX + urllib.parse.quote(doi, safe=""))
    return parse_openalex(data, doi)


_CITATION_PDF = (
    re.compile(
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
        re.IGNORECASE,
    ),
)


def citation_pdf_url(html: str) -> str | None:
    """The Highwire `citation_pdf_url` meta tag - emitted by most publishers."""
    for pattern in _CITATION_PDF:
        match = pattern.search(html)
        if match:
            return match.group(1)
    return None


def publisher_pdf_url(page_url: str) -> str | None:
    """Per-publisher PDF URL for sites that omit the citation_pdf_url meta."""
    if "cell.com" in page_url and "/fulltext/" in page_url:
        return page_url.replace("/fulltext/", "/pdf/") + ".pdf"
    if "science.org/doi/" in page_url:
        return re.sub(r"/doi/(full/|abs/)?", "/doi/pdf/", page_url, count=1)
    return None


# ScienceDirect embeds the (token-bearing) PDF URL parts in a JSON island rather
# than a citation_pdf_url meta. The article page carries pdfDownload.urlMetadata
# with the per-session md5/pid, so the link is reconstructable from the rendered
# HTML (same approach as Zotero's translator) - no extra token call needed.
_SD_URLMETA = re.compile(
    r'"urlMetadata"\s*:\s*\{'
    r'\s*"queryParams"\s*:\s*\{\s*"md5"\s*:\s*"([0-9a-f]+)"\s*,'
    r'\s*"pid"\s*:\s*"([^"]+)"\s*\}\s*,'
    r'\s*"pii"\s*:\s*"([^"]+)"\s*,'
    r'\s*"pdfExtension"\s*:\s*"([^"]+)"\s*,'
    r'\s*"path"\s*:\s*"([^"]+)"',
    re.IGNORECASE,
)


def sciencedirect_pdf_url(html: str, base_url: str) -> str | None:
    """Reconstruct the ScienceDirect PDF URL from the page's pdfDownload JSON."""
    match = _SD_URLMETA.search(html)
    if match is None:
        return None
    md5, pid, pii, ext, path = match.groups()
    query = urllib.parse.urlencode({"md5": md5, "pid": pid})
    return urllib.parse.urljoin(base_url, f"/{path}/{pii}{ext}?{query}")


# Cell Press journals: ISSN (PII prefix) -> cell.com slug. A Cell DOI resolves
# via doi.org to Elsevier's linkinghub / ScienceDirect, but the same article is
# on cell.com keyed by the same PII, where the PDF is reachable.
_CELL_ISSN_SLUG = {
    "00928674": "cell",
    "10972765": "molecular-cell",
    "22111247": "cell-reports",
    "10747613": "immunity",
    "08966273": "neuron",
    "09609822": "current-biology",
    "15345807": "developmental-cell",
    "19345909": "cell-stem-cell",
    "15356108": "cancer-cell",
    "15504131": "cell-metabolism",
    "10974172": "cell",
    "25890042": "iscience",
    "26663791": "cell-reports-medicine",
}
_SD_PII = re.compile(r"/pii/(S\d{16})", re.IGNORECASE)


def cellpress_article_url(url: str) -> str | None:
    """cell.com article URL for an Elsevier/ScienceDirect Cell Press PII URL."""
    if "elsevier.com" not in url and "sciencedirect.com" not in url:
        return None
    match = _SD_PII.search(url)
    if match is None:
        return None
    raw = match.group(1)[1:]
    slug = _CELL_ISSN_SLUG.get(raw[:8])
    if slug is None:
        return None
    pii = f"S{raw[0:4]}-{raw[4:8]}({raw[8:10]}){raw[10:15]}-{raw[15]}"
    return f"https://www.cell.com/{slug}/fulltext/{pii}"


def pdf_candidates(links: list[str]) -> list[str]:
    """Links that look like a PDF, for the manifest's escape-hatch list."""
    out: list[str] = []
    for link in links:
        low = link.lower()
        if (".pdf" in low or "/pdf/" in low) and link not in out:
            out.append(link)
    return out


def download_file(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310
            ctype = response.headers.get("content-type", "").lower()
            if "html" in ctype:
                msg = (
                    f"OA link returned an HTML page, not a PDF "
                    f"(likely bot-blocked): {url}"
                )
                raise CLIError(msg, EXIT_UNRESOLVED)
            with dest.open("wb") as handle:
                shutil.copyfileobj(response, handle)
    except (urllib.error.URLError, TimeoutError) as exc:
        msg = f"download failed: {exc}"
        raise CLIError(msg, EXIT_FETCH) from exc
