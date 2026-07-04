"""Paper metadata + open-access resolution via keyless JSON APIs.

OpenAlex returns DOI metadata and broad open-access hints. Europe PMC / PMC OA
adds native legal full-text coverage for biomedical papers and identifier inputs
(PMID / PMCID), and Unpaywall adds independent DOI OA coverage when configured
with a contact email. The browser is only needed later for paywalled full text /
PDF.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Literal
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree

from paperfetch_cli.errors import EXIT_FETCH, EXIT_UNRESOLVED, CLIError

if TYPE_CHECKING:
    from pathlib import Path

_DOI_RE = re.compile(r"10\.\d{4,9}/\S+")
_BIORXIV_HOSTS = ("biorxiv.org", "medrxiv.org")
_ARXIV_API = "https://export.arxiv.org/api/query?id_list="
_PMCID_RE = re.compile(r"\bPMC\d+\b", re.IGNORECASE)
_PMID_MARKED_RE = re.compile(
    r"(?:\bPMID\s*:?\s*|pubmed\.ncbi\.nlm\.nih\.gov/|europepmc\.org/article/MED/)"
    r"(\d{1,9})\b",
    re.IGNORECASE,
)
_OPENALEX = "https://api.openalex.org/works/doi:"
_EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_PMC_OA = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id="
_UNPAYWALL = "https://api.unpaywall.org/v2/"
_TIMEOUT = 20
_UA = "paperfetch-cli (https://github.com/mulatta/skillz)"

IdentifierKind = Literal["doi", "url", "arxiv", "pmid", "pmcid"]


@dataclass(frozen=True)
class ParsedIdentifier:
    kind: IdentifierKind
    value: str
    is_url: bool = False


@dataclass
class PaperMeta:
    doi: str
    title: str = ""
    authors: tuple[str, ...] = ()
    journal: str = ""
    year: int | None = None
    oa_pdf_url: str | None = None
    landing_url: str | None = None
    pmid: str = ""
    pmcid: str = ""
    arxiv_id: str = ""
    oa_pdf_source: str = "oa"
    oa_landing_url: str | None = None


def _looks_like_url(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def normalize_biorxiv_url_doi(value: str) -> str | None:
    parsed = urllib.parse.urlparse(value.strip())
    host = parsed.netloc.lower()
    if not any(_host_matches(host, item) for item in _BIORXIV_HOSTS):
        return None
    match = re.search(r"/content/[^?#]*(10\.1101/[^/?#]+)", parsed.path)
    if match is None:
        return None
    doi = urllib.parse.unquote(match.group(1))
    for suffix in (
        ".full.pdf",
        ".full",
        ".abstract",
        ".article-info",
        ".external-links",
    ):
        if doi.lower().endswith(suffix):
            doi = doi[: -len(suffix)]
    doi = re.sub(r"v\d+$", "", doi, flags=re.IGNORECASE)
    return doi.rstrip(").,;>").lower()


def normalize_doi(value: str) -> str | None:
    biorxiv_doi = normalize_biorxiv_url_doi(value)
    if biorxiv_doi is not None:
        return biorxiv_doi
    match = _DOI_RE.search(value.strip())
    if match is None:
        return None
    return match.group(0).rstrip(").,;>").lower()


_ARXIV_NEW_RE = re.compile(r"\d{4}\.\d{4,5}(?:v\d+)?", re.IGNORECASE)
_ARXIV_OLD_RE = re.compile(
    r"[a-z][a-z-]*(?:\.[A-Za-z]{2})?/\d{7}(?:v\d+)?",
    re.IGNORECASE,
)


def normalize_arxiv_id(value: str) -> str | None:
    target = value.strip()
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme in {"http", "https"} and _host_matches(
        parsed.netloc.lower(), "arxiv.org"
    ):
        parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"abs", "pdf", "html"}:
            target = "/".join(parts[1:])
    if target.lower().startswith("arxiv:"):
        target = target.split(":", 1)[1].strip()
    if target.lower().endswith(".pdf"):
        target = target[:-4]
    if _ARXIV_NEW_RE.fullmatch(target) or _ARXIV_OLD_RE.fullmatch(target):
        return target
    return None


def normalize_pmcid(value: str) -> str | None:
    match = _PMCID_RE.search(value.strip())
    if match is None:
        return None
    return match.group(0).upper()


def normalize_pmid(value: str) -> str | None:
    stripped = value.strip()
    if stripped.isdecimal() and 1 <= len(stripped) <= 9:
        return stripped
    match = _PMID_MARKED_RE.search(stripped)
    if match is None:
        return None
    return match.group(1)


def parse_identifier(value: str) -> ParsedIdentifier | None:
    target = value.strip()
    is_url = _looks_like_url(target)
    doi = normalize_doi(target)
    if doi is not None:
        return ParsedIdentifier("doi", doi, is_url=is_url)
    arxiv_id = normalize_arxiv_id(target)
    if arxiv_id is not None:
        return ParsedIdentifier("arxiv", arxiv_id, is_url=is_url)
    pmcid = normalize_pmcid(target)
    if pmcid is not None:
        return ParsedIdentifier("pmcid", pmcid, is_url=is_url)
    pmid = normalize_pmid(target)
    if pmid is not None:
        return ParsedIdentifier("pmid", pmid, is_url=is_url)
    if is_url:
        return ParsedIdentifier("url", target, is_url=True)
    return None


def _get_json(url: str, source: str = "metadata") -> dict[str, object]:
    request = urllib.request.Request(  # noqa: S310 - https URL built from constants
        url,
        headers={"User-Agent": _UA, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310
            payload: object = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        msg = f"{source} lookup failed: {exc}"
        raise CLIError(msg, EXIT_UNRESOLVED) from exc
    if not isinstance(payload, dict):
        msg = f"unexpected {source} response"
        raise CLIError(msg, EXIT_UNRESOLVED)
    return payload


def _get_text(url: str, accept: str) -> str:
    request = urllib.request.Request(  # noqa: S310 - https URL built from constants
        url,
        headers={"User-Agent": _UA, "Accept": accept},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310
            data: bytes = response.read()
            return data.decode("utf-8")
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
        msg = f"metadata lookup failed: {exc}"
        raise CLIError(msg, EXIT_UNRESOLVED) from exc


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


def _unpaywall_authors(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        author = _dict(item)
        name = _str(author.get("name"))
        if not name:
            name = " ".join(
                part
                for part in (
                    _str(author.get("given")),
                    _str(author.get("family")),
                )
                if part
            )
        if name:
            names.append(name)
    return tuple(names)


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


def _europepmc_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def europepmc_search_url(
    *, doi: str | None = None, pmid: str | None = None, pmcid: str | None = None
) -> str:
    if doi:
        query = f'DOI:"{_europepmc_quote(doi)}"'
    elif pmcid:
        query = f"PMCID:{pmcid}"
    elif pmid:
        query = f"EXT_ID:{pmid} AND SRC:MED"
    else:
        msg = "expected DOI, PMID, or PMCID for Europe PMC lookup"
        raise CLIError(msg, EXIT_UNRESOLVED)
    params = urllib.parse.urlencode(
        {"query": query, "format": "json", "resultType": "core", "pageSize": "1"}
    )
    return f"{_EUROPEPMC_SEARCH}?{params}"


def _europepmc_authors(result: dict[str, object]) -> tuple[str, ...]:
    authors = _dict(result.get("authorList")).get("author")
    if isinstance(authors, list):
        names = [_str(_dict(author).get("fullName")) for author in authors]
        return tuple(name for name in names if name)
    author_string = _str(result.get("authorString"))
    if not author_string:
        return ()
    return tuple(name.strip() for name in author_string.split(",") if name.strip())


def _year(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value[:4].isdecimal():
        return int(value[:4])
    return None


def _europepmc_landing(result: dict[str, object]) -> str | None:
    pmcid = _str(result.get("pmcid"))
    if pmcid:
        return f"https://europepmc.org/articles/{pmcid}"
    pmid = _str(result.get("pmid"))
    if pmid:
        return f"https://europepmc.org/article/MED/{pmid}"
    doi = _str(result.get("doi"))
    if doi:
        return f"https://doi.org/{doi}"
    return None


def _is_open_access(result: dict[str, object], item: dict[str, object]) -> bool:
    code = _str(item.get("availabilityCode")).upper()
    availability = _str(item.get("availability")).lower()
    result_oa = _str(result.get("isOpenAccess")).upper() == "Y"
    return result_oa or code == "OA" or "open access" in availability


def _europepmc_pdf_url(result: dict[str, object]) -> str | None:
    urls = _dict(result.get("fullTextUrlList")).get("fullTextUrl")
    candidates: list[tuple[int, str]] = []
    if isinstance(urls, list):
        for raw_item in urls:
            item = _dict(raw_item)
            url = _str(item.get("url"))
            style = _str(item.get("documentStyle")).lower()
            if not url or style != "pdf" or not _is_open_access(result, item):
                continue
            site = _str(item.get("site")).lower()
            score = 0 if site in {"europe_pmc", "pubmed central", "pmc"} else 1
            if url.startswith("https://"):
                score -= 1
            candidates.append((score, url))
    if candidates:
        return min(candidates, key=lambda candidate: candidate[0])[1]
    pmcid = _str(result.get("pmcid"))
    if pmcid and _str(result.get("isOpenAccess")).upper() == "Y":
        return f"https://europepmc.org/articles/{pmcid}?pdf=render"
    return None


def parse_europepmc(
    data: dict[str, object],
    *,
    doi: str | None = None,
    pmid: str | None = None,
    pmcid: str | None = None,
) -> PaperMeta | None:
    results = _dict(data.get("resultList")).get("result")
    if not isinstance(results, list) or not results:
        return None
    result = _dict(results[0])
    resolved_doi = (_str(result.get("doi")) or doi or "").lower()
    resolved_pmid = _str(result.get("pmid")) or pmid or ""
    resolved_pmcid = (_str(result.get("pmcid")) or pmcid or "").upper()
    pdf_url = _europepmc_pdf_url(result)
    landing = _europepmc_landing(result)
    return PaperMeta(
        doi=resolved_doi,
        title=_str(result.get("title")),
        authors=_europepmc_authors(result),
        journal=_str(result.get("journalTitle")),
        year=_year(result.get("pubYear") or result.get("firstPublicationDate")),
        oa_pdf_url=pdf_url,
        landing_url=landing,
        pmid=resolved_pmid,
        pmcid=resolved_pmcid,
        oa_pdf_source="europepmc" if pdf_url else "oa",
        oa_landing_url=landing if pdf_url else None,
    )


class _PmcOaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pdf_url = ""
        self._record_retracted = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "record":
            self._record_retracted = attr.get("retracted", "").lower() == "yes"
        if (
            tag.lower() == "link"
            and not self._record_retracted
            and attr.get("format", "").lower() == "pdf"
            and not self.pdf_url
        ):
            self.pdf_url = attr.get("href", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "record":
            self._record_retracted = False


def _https_ftp_ncbi(url: str) -> str:
    if url.startswith("ftp://ftp.ncbi.nlm.nih.gov/"):
        return "https://ftp.ncbi.nlm.nih.gov/" + url.removeprefix(
            "ftp://ftp.ncbi.nlm.nih.gov/"
        )
    return url


def _deprecated_pmc_url(url: str) -> str | None:
    prefix = "https://ftp.ncbi.nlm.nih.gov/pub/pmc/"
    if url.startswith(prefix) and not url.startswith(prefix + "deprecated/"):
        return prefix + "deprecated/" + url.removeprefix(prefix)
    return None


def parse_pmc_oa_pdf(xml_text: str) -> str | None:
    parser = _PmcOaParser()
    parser.feed(xml_text)
    href = _https_ftp_ncbi(parser.pdf_url)
    if href.startswith(("https://", "http://")):
        return href
    return None


def resolve_pmc_oa_pdf(pmcid: str) -> str | None:
    xml_text = _get_text(
        _PMC_OA + urllib.parse.quote(pmcid, safe=""), "application/xml"
    )
    return parse_pmc_oa_pdf(xml_text)


def resolve_europepmc(
    *, doi: str | None = None, pmid: str | None = None, pmcid: str | None = None
) -> PaperMeta:
    data = _get_json(europepmc_search_url(doi=doi, pmid=pmid, pmcid=pmcid))
    meta = parse_europepmc(data, doi=doi, pmid=pmid, pmcid=pmcid)
    if meta is None:
        msg = "Europe PMC lookup found no matching record"
        raise CLIError(msg, EXIT_UNRESOLVED)
    if meta.pmcid and not meta.oa_pdf_url:
        with contextlib.suppress(CLIError):
            if pdf_url := resolve_pmc_oa_pdf(meta.pmcid):
                meta.oa_pdf_url = pdf_url
                meta.oa_pdf_source = "pmc_oa"
                meta.oa_landing_url = meta.landing_url
    return meta


def _location_pdf_url(location: dict[str, object]) -> str | None:
    return _str(location.get("url_for_pdf")) or None


def _location_landing_url(location: dict[str, object]) -> str | None:
    return (
        _str(location.get("url_for_landing_page")) or _str(location.get("url")) or None
    )


def _best_unpaywall_pdf(data: dict[str, object]) -> str | None:
    best = _dict(data.get("best_oa_location"))
    pdf_url = _location_pdf_url(best)
    if pdf_url:
        return pdf_url
    locations = data.get("oa_locations")
    if not isinstance(locations, list):
        return None
    for item in locations:
        pdf_url = _location_pdf_url(_dict(item))
        if pdf_url:
            return pdf_url
    return None


def _best_unpaywall_landing(data: dict[str, object]) -> str | None:
    best = _dict(data.get("best_oa_location"))
    landing_url = _location_landing_url(best)
    if landing_url:
        return landing_url
    return _str(data.get("doi_url")) or None


def parse_unpaywall(data: dict[str, object], doi: str) -> PaperMeta:
    year = data.get("year")
    pdf_url = _best_unpaywall_pdf(data)
    return PaperMeta(
        doi=doi,
        title=_str(data.get("title")),
        authors=_unpaywall_authors(data.get("z_authors")),
        journal=_str(data.get("journal_name")),
        year=year if isinstance(year, int) else None,
        oa_pdf_url=pdf_url,
        landing_url=_best_unpaywall_landing(data),
        oa_pdf_source="unpaywall" if pdf_url else "oa",
    )


def resolve_unpaywall(doi: str, email: str | None) -> PaperMeta | None:
    email = email.strip() if email else ""
    if not email:
        return None
    query = urllib.parse.urlencode({"email": email})
    data = _get_json(
        f"{_UNPAYWALL}{urllib.parse.quote(doi, safe='')}?{query}",
        "Unpaywall",
    )
    return parse_unpaywall(data, doi)


def _merge_metadata(primary: PaperMeta, fallback: PaperMeta) -> PaperMeta:
    use_fallback_pdf = primary.oa_pdf_url is None and fallback.oa_pdf_url is not None
    return PaperMeta(
        doi=primary.doi or fallback.doi,
        title=primary.title or fallback.title,
        authors=primary.authors or fallback.authors,
        journal=primary.journal or fallback.journal,
        year=primary.year or fallback.year,
        oa_pdf_url=primary.oa_pdf_url or fallback.oa_pdf_url,
        landing_url=primary.landing_url or fallback.landing_url,
        pmid=primary.pmid or fallback.pmid,
        pmcid=primary.pmcid or fallback.pmcid,
        arxiv_id=primary.arxiv_id or fallback.arxiv_id,
        oa_pdf_source=fallback.oa_pdf_source
        if use_fallback_pdf
        else primary.oa_pdf_source,
        oa_landing_url=primary.oa_landing_url or fallback.oa_landing_url,
    )


def resolve_metadata(doi: str, unpaywall_email: str | None = None) -> PaperMeta:
    openalex_error: CLIError | None = None
    openalex_meta: PaperMeta | None = None
    try:
        data = _get_json(_OPENALEX + urllib.parse.quote(doi, safe=""), "OpenAlex")
        openalex_meta = parse_openalex(data, doi)
    except CLIError as exc:
        openalex_error = exc
    if openalex_meta is not None and openalex_meta.oa_pdf_url:
        return openalex_meta
    try:
        unpaywall_meta = resolve_unpaywall(doi, unpaywall_email)
    except CLIError:
        unpaywall_meta = None
    if openalex_meta is not None:
        if unpaywall_meta is None:
            return openalex_meta
        return _merge_metadata(openalex_meta, unpaywall_meta)
    if unpaywall_meta is not None:
        return unpaywall_meta
    if openalex_error is not None:
        raise openalex_error
    msg = "metadata lookup failed"
    raise CLIError(msg, EXIT_UNRESOLVED)


def arxiv_paper_meta(arxiv_id: str) -> PaperMeta:
    escaped = urllib.parse.quote(arxiv_id, safe="/.")
    return PaperMeta(
        doi="",
        oa_pdf_url=f"https://arxiv.org/pdf/{escaped}.pdf",
        landing_url=f"https://arxiv.org/abs/{escaped}",
        arxiv_id=arxiv_id,
        oa_pdf_source="arxiv",
        oa_landing_url=f"https://arxiv.org/abs/{escaped}",
    )


_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV_ATOM = "{http://arxiv.org/schemas/atom}"


def _xml_text(element: Element, name: str) -> str:
    child = element.find(name)
    if child is None or child.text is None:
        return ""
    return " ".join(child.text.split())


def resolve_arxiv_metadata(arxiv_id: str) -> PaperMeta:
    payload = _get_text(
        _ARXIV_API + urllib.parse.quote(arxiv_id, safe="/"),
        "application/atom+xml",
    )
    try:
        root = ElementTree.fromstring(payload)
    except ParseError as exc:
        msg = f"metadata lookup failed: {exc}"
        raise CLIError(msg, EXIT_UNRESOLVED) from exc
    entry = root.find(f"{_ATOM}entry")
    if entry is None:
        msg = f"arXiv metadata not found for {arxiv_id}"
        raise CLIError(msg, EXIT_UNRESOLVED)
    authors = tuple(
        name
        for author in entry.findall(f"{_ATOM}author")
        if (name := _xml_text(author, f"{_ATOM}name"))
    )
    published = _xml_text(entry, f"{_ATOM}published")
    year = int(published[:4]) if re.fullmatch(r"\d{4}.*", published) else None
    meta = arxiv_paper_meta(arxiv_id)
    meta.doi = normalize_doi(_xml_text(entry, f"{_ARXIV_ATOM}doi")) or ""
    meta.title = _xml_text(entry, f"{_ATOM}title")
    meta.authors = authors
    meta.journal = _xml_text(entry, f"{_ARXIV_ATOM}journal_ref")
    meta.year = year
    return meta


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
    parsed = urllib.parse.urlsplit(page_url)
    host = parsed.netloc.lower()
    if _host_matches(host, "cell.com") and "/fulltext/" in parsed.path:
        return urllib.parse.urlunsplit(
            parsed._replace(path=parsed.path.replace("/fulltext/", "/pdf/") + ".pdf")
        )
    if _host_matches(host, "science.org") and parsed.path.startswith("/doi/"):
        return urllib.parse.urlunsplit(
            parsed._replace(
                path=re.sub(r"/doi/(full/|abs/)?", "/doi/pdf/", parsed.path, count=1)
            )
        )
    return None


# ScienceDirect embeds the (token-bearing) PDF URL parts in a JSON island rather
# than a citation_pdf_url meta. The article page carries pdfDownload.urlMetadata
# with the per-session md5/pid, so the link is reconstructable from the rendered
# HTML (same approach as Zotero's translator) - no extra token call needed.
_SD_PDF_DOWNLOAD = re.compile(r'"pdfDownload"\s*:', re.IGNORECASE)


def _json_object_after(html: str, start: int) -> dict[str, object] | None:
    opener = html.find("{", start)
    if opener < 0:
        return None
    try:
        value, _end = json.JSONDecoder().raw_decode(html[opener:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def sciencedirect_pdf_url(html: str, base_url: str) -> str | None:
    """Reconstruct the ScienceDirect PDF URL from the page's pdfDownload JSON."""
    match = _SD_PDF_DOWNLOAD.search(html)
    if match is None:
        return None
    pdf_download = _json_object_after(html, match.end())
    if pdf_download is None:
        return None
    metadata = _dict(pdf_download.get("urlMetadata"))
    query_params = _dict(metadata.get("queryParams"))
    md5 = _str(query_params.get("md5"))
    pid = _str(query_params.get("pid"))
    pii = _str(metadata.get("pii"))
    ext = _str(metadata.get("pdfExtension"))
    path = _str(metadata.get("path"))
    if not all((md5, pid, pii, ext, path)):
        return None
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
    host = urllib.parse.urlsplit(url).netloc.lower()
    if not (
        _host_matches(host, "elsevier.com") or _host_matches(host, "sciencedirect.com")
    ):
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


def _download_pdf_once(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})  # noqa: S310
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310
        ctype = response.headers.get("content-type", "").lower()
        if "html" in ctype:
            msg = (
                f"OA link returned an HTML page, not a PDF (likely bot-blocked): {url}"
            )
            raise CLIError(msg, EXIT_UNRESOLVED)
        prefix = response.read(5)
        if prefix != b"%PDF-":
            msg = f"OA link returned bytes that are not a PDF: {url}"
            raise CLIError(msg, EXIT_UNRESOLVED)
        with dest.open("wb") as handle:
            handle.write(prefix)
            shutil.copyfileobj(response, handle)


def download_file(url: str, dest: Path) -> None:
    candidates = [url]
    if deprecated := _deprecated_pmc_url(url):
        candidates.append(deprecated)
    last_error: urllib.error.URLError | TimeoutError | None = None
    for candidate in candidates:
        try:
            _download_pdf_once(candidate, dest)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 404 and candidate != candidates[-1]:
                continue
            break
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            break
        else:
            return
    msg = f"download failed: {last_error}"
    raise CLIError(msg, EXIT_FETCH) from last_error
