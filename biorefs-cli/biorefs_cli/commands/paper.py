"""PubMed/PMC-backed paper commands."""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, cast

from biorefs_cli.config import Config, load_config
from biorefs_cli.errors import CLIError, HTTPError, RateLimitError
from biorefs_cli.http import HttpClient, JsonObject
from biorefs_cli.ncbi_client import TOOL_NAME, NCBIClient
from biorefs_cli.output import markdown_heading, print_json

IDCONV_URL = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
CROSSREF_URL = "https://api.crossref.org/works"
DOI_RESOLVER_URL = "https://doi.org"
DEFAULT_LIMIT = 20
DEFAULT_INCLUDE = {"abstract", "authors", "ids"}
ALL_INCLUDE = {"abstract", "authors", "mesh", "grants", "ids"}
SECTION_TYPES = {
    "method": "methods",
    "methods": "methods",
    "materials and methods": "methods",
    "result": "results",
    "results": "results",
    "discussion": "discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "introduction": "introduction",
    "background": "introduction",
}

JsonDict = dict[str, Any]
Printer = Callable[[JsonDict], None]


class PaperInputError(CLIError):
    """User-facing validation error for paper commands."""


class PaperClient:
    """Small paper-specific wrapper over shared scaffold clients."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.ncbi = NCBIClient.from_config(config)
        self.http = HttpClient(timeout_seconds=config.timeout_seconds)

    def esearch_pubmed(
        self,
        query: str,
        *,
        limit: int,
        since: str | None,
        until: str | None,
    ) -> JsonObject:
        params: dict[str, str | int] = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": limit,
        }
        if since or until:
            params["datetype"] = "pdat"
        if since:
            params["mindate"] = since
        if until:
            params["maxdate"] = until
        return self.ncbi.request_json("esearch", params)

    def efetch_pubmed(self, pmids: Sequence[str]) -> str:
        if not pmids:
            return ""
        url = self.ncbi.eutils_url(
            "efetch",
            {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
        )
        return self.http.get(
            url,
            rate_limit_source=self.ncbi.rate_limit_source(),
        ).body.decode("utf-8")

    def efetch_pmc(self, pmcid: str) -> str:
        url = self.ncbi.eutils_url(
            "efetch",
            {"db": "pmc", "id": normalize_pmcid(pmcid), "retmode": "xml"},
        )
        return self.http.get(
            url,
            rate_limit_source=self.ncbi.rate_limit_source(),
        ).body.decode("utf-8")

    def elink_pubmed(self, pmid: str, *, mode: str) -> JsonObject:
        cmd = "neighbor_score" if mode == "similar" else "neighbor"
        return self.ncbi.request_json(
            "elink",
            {
                "dbfrom": "pubmed",
                "db": "pubmed",
                "id": normalize_pmid(pmid),
                "cmd": cmd,
                "retmode": "json",
            },
        )

    def id_convert(self, kind: str, value: str) -> JsonDict:
        identifier = normalize_identifier(kind, value)
        params = self.ncbi.common_params() | {"ids": identifier, "format": "json"}
        url = f"{IDCONV_URL}?{urllib.parse.urlencode(params)}"
        raw = self.http.get_json(
            url,
            rate_limit_source=self.ncbi.rate_limit_source("pmc-id-converter"),
        )
        return normalize_idconv(identifier, raw)

    def resolve_pmid(
        self, kind: str, value: str
    ) -> tuple[str | None, list[str], JsonDict | None]:
        if kind == "pmid":
            return normalize_pmid(value), [], None
        warnings: list[str] = []
        converted = self.id_convert(kind, value)
        identifiers = as_dict(converted.get("identifiers"))
        pmid = identifiers.get("pmid")
        if isinstance(pmid, str) and pmid:
            return pmid, warnings, converted
        warnings.append("pmc-id-converter:no-pmid")
        if kind == "doi":
            search = self.esearch_pubmed(
                f"{normalize_doi(value)}[doi]", limit=2, since=None, until=None
            )
            ids = extract_esearch_ids(search)
            if len(ids) == 1:
                return ids[0], warnings, converted
            warnings.append(
                "doi-not-found-in-pubmed" if not ids else "doi-ambiguous-in-pubmed"
            )
        return None, warnings, converted

    def crossref_work(self, doi: str) -> JsonDict:
        normalized = normalize_doi(doi)
        params: dict[str, str] = {}
        if self.config.email:
            params["mailto"] = self.config.email
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        encoded = urllib.parse.quote(normalized, safe="")
        raw = self.http.get_json(
            f"{CROSSREF_URL}/{encoded}{query}", rate_limit_source="crossref"
        )
        message = raw.get("message")
        if not isinstance(message, dict):
            return {
                "status": "unresolved",
                "identifiers": {"doi": normalized},
                "warnings": ["crossref:no-message"],
            }
        return normalize_crossref_work(cast("dict[str, Any]", message))

    def crossref_export(self, doi: str, accept: str) -> str | None:
        normalized = normalize_doi(doi)
        headers = {"Accept": accept, "User-Agent": user_agent(self.config)}
        response = self.http.get(
            f"{DOI_RESOLVER_URL}/{urllib.parse.quote(normalized, safe='/')}",
            headers=headers,
            rate_limit_source="crossref",
        )
        text = response.body.decode("utf-8", errors="replace").strip()
        return text or None


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("paper", help="PubMed/PMC paper workflows")
    paper_subcommands = parser.add_subparsers(dest="paper_command", required=True)

    search = paper_subcommands.add_parser("search", help="Search papers")
    search.add_argument("query")
    search.add_argument(
        "--source",
        choices=("pubmed", "europepmc", "openalex", "crossref"),
        default="pubmed",
    )
    search.add_argument("--since", metavar="YEAR")
    search.add_argument("--until", metavar="YEAR")
    search.add_argument("--type")
    search.add_argument("--limit", type=positive_int, default=DEFAULT_LIMIT)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=handle)

    fetch = paper_subcommands.add_parser("fetch", help="Fetch paper metadata")
    fetch.add_argument("--pmid")
    fetch.add_argument("--pmcid")
    fetch.add_argument("--doi")
    fetch.add_argument("--include", default="abstract,authors,ids")
    fetch.add_argument("--json", action="store_true")
    fetch.set_defaults(handler=handle)

    fulltext = paper_subcommands.add_parser(
        "fulltext", help="Fetch open-access full text"
    )
    fulltext.add_argument("--pmid")
    fulltext.add_argument("--pmcid")
    fulltext.add_argument("--doi")
    fulltext.add_argument("--sections")
    fulltext.add_argument(
        "--source", choices=("pmc", "europepmc", "auto"), default="auto"
    )
    fulltext.add_argument("--json", action="store_true")
    fulltext.set_defaults(handler=handle)

    convert = paper_subcommands.add_parser("convert", help="Convert paper identifiers")
    convert.add_argument("--pmid")
    convert.add_argument("--pmcid")
    convert.add_argument("--doi")
    convert.add_argument("--json", action="store_true")
    convert.set_defaults(handler=handle)

    cite = paper_subcommands.add_parser("cite", help="Export citations")
    cite.add_argument("--pmid")
    cite.add_argument("--pmcid")
    cite.add_argument("--doi")
    cite.add_argument(
        "--format", choices=("markdown", "bibtex", "ris", "json"), default="markdown"
    )
    cite.add_argument("--strict", action="store_true")
    cite.set_defaults(handler=handle)

    related = paper_subcommands.add_parser("related", help="Find related papers")
    related.add_argument("--pmid")
    related.add_argument("--doi")
    related.add_argument(
        "--mode", choices=("similar", "references", "cited-by"), default="similar"
    )
    related.add_argument("--limit", type=positive_int, default=DEFAULT_LIMIT)
    related.add_argument("--json", action="store_true")
    related.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    config = load_config()
    client = PaperClient(config)
    command = str(args.paper_command)
    try:
        if command == "search":
            result = cmd_search(client, args)
            emit(result, use_json=bool(args.json), printer=print_search)
        elif command == "fetch":
            result = cmd_fetch(client, args)
            emit(result, use_json=bool(args.json), printer=print_fetch)
        elif command == "convert":
            result = cmd_convert(client, args)
            emit(result, use_json=bool(args.json), printer=print_convert)
        elif command == "fulltext":
            result = cmd_fulltext(client, args)
            emit(result, use_json=bool(args.json), printer=print_fulltext)
        elif command == "cite":
            print(cmd_cite(client, args))
        elif command == "related":
            result = cmd_related(client, args)
            emit(result, use_json=bool(args.json), printer=print_related)
        else:
            msg = f"unknown paper command: {command}"
            raise PaperInputError(msg, exit_code=2)
    except RateLimitError as exc:
        if command == "convert" or bool(getattr(args, "json", False)):
            print_json(rate_limited_payload(exc))
            return 1
        raise
    return 0


def cmd_search(client: PaperClient, args: argparse.Namespace) -> JsonDict:
    if args.source != "pubmed":
        return unsupported(
            "search",
            str(args.source),
            f"search --source {args.source} is not implemented",
        )
    query = pubmed_query(str(args.query), args.type)
    raw = client.esearch_pubmed(
        query, limit=int(args.limit), since=args.since, until=args.until
    )
    ids = extract_esearch_ids(raw)
    records = (
        parse_pubmed_xml(client.efetch_pubmed(ids), DEFAULT_INCLUDE) if ids else []
    )
    esearch = as_dict(raw.get("esearchresult"))
    return {
        "source": "pubmed",
        "query": args.query,
        "pubmed_query": query,
        "translation": esearch.get("querytranslation"),
        "count": int(str(esearch.get("count", "0"))),
        "limit": args.limit,
        "ids": ids,
        "records": records,
        "provenance": [{"source": "pubmed-esearch"}, {"source": "pubmed-efetch"}],
    }


def cmd_fetch(client: PaperClient, args: argparse.Namespace) -> JsonDict:
    kind, value = one_identifier(args.pmid, args.pmcid, args.doi)
    return fetch_record(client, kind, value, parse_include(str(args.include)))


def cmd_convert(client: PaperClient, args: argparse.Namespace) -> JsonDict:
    kind, value = one_identifier(args.pmid, args.pmcid, args.doi)
    try:
        return client.id_convert(kind, value)
    except RateLimitError as exc:
        payload = rate_limited_payload(exc)
        payload["input"] = {kind: value}
        return payload


def cmd_fulltext(client: PaperClient, args: argparse.Namespace) -> JsonDict:
    kind, value = one_identifier(args.pmid, args.pmcid, args.doi)
    wanted_sections = parse_sections(args.sections)
    if args.source == "europepmc":
        return europepmc_unavailable(kind, value)
    pmcid = value if kind == "pmcid" else None
    tried: list[JsonDict] = []
    if pmcid is None:
        converted = client.id_convert(kind, value)
        tried.append(
            {"source": "pmc-id-converter", "status": converted.get("status", "unknown")}
        )
        identifiers = as_dict(converted.get("identifiers"))
        converted_pmcid = identifiers.get("pmcid")
        if isinstance(converted_pmcid, str):
            pmcid = converted_pmcid
    if pmcid is None:
        metadata = metadata_or_unavailable(client, kind, value)
        status = (
            "abstract-only"
            if as_dict(metadata.get("abstract")).get("text")
            else "metadata-only"
        )
        metadata["fulltext"] = {"status": status, "reason": "no-pmcid", "tried": tried}
        metadata["evidence_level"] = status
        return metadata
    xml_text = client.efetch_pmc(pmcid)
    record = parse_jats_xml(xml_text, wanted_sections)
    fulltext = as_dict(record.get("fulltext"))
    if fulltext.get("status") == "unavailable":
        fulltext.setdefault("tried", tried)
    return record


def cmd_cite(client: PaperClient, args: argparse.Namespace) -> str:
    kind, value = one_identifier(args.pmid, args.pmcid, args.doi)
    record = fetch_record(client, kind, value, DEFAULT_INCLUDE)
    if record.get("status") == "unresolved" and kind == "doi":
        record = client.crossref_work(value)
    if bool(args.strict):
        strict_validate(record)
    fmt = str(args.format)
    doi = as_dict(record.get("identifiers")).get("doi")
    if kind == "doi" and isinstance(doi, str) and fmt in {"bibtex", "ris"}:
        accept = (
            "application/x-bibtex"
            if fmt == "bibtex"
            else "application/x-research-info-systems"
        )
        try:
            exported = client.crossref_export(doi, accept)
        except HTTPError:
            exported = None
        if exported:
            return exported
    return format_citation(record, fmt)


def cmd_related(client: PaperClient, args: argparse.Namespace) -> JsonDict:
    kind, value = one_identifier(args.pmid, None, args.doi)
    mode = str(args.mode)
    if kind != "pmid" or mode != "similar":
        return unsupported(
            "related", mode, "only PMID similar is implemented in this MVP"
        )
    raw = client.elink_pubmed(value, mode=mode)
    related = parse_elink_ids(raw)[: int(args.limit)]
    records = (
        parse_pubmed_xml(client.efetch_pubmed(related), DEFAULT_INCLUDE)
        if related
        else []
    )
    return {
        "source": "pubmed-elink",
        "mode": mode,
        "input": {"pmid": value},
        "ids": related,
        "records": records,
        "provenance": [{"source": "pubmed-elink"}],
    }


def fetch_record(
    client: PaperClient, kind: str, value: str, include: set[str]
) -> JsonDict:
    pmid, warnings, converted = client.resolve_pmid(kind, value)
    if pmid is None:
        identifiers = {kind: value}
        if converted:
            identifiers.update(as_dict(converted.get("identifiers")))
        return {
            "status": "unresolved",
            "identifiers": identifiers,
            "warnings": warnings,
            "provenance": [{"source": "pubmed"}],
        }
    records = parse_pubmed_xml(client.efetch_pubmed([pmid]), include)
    if not records:
        return {
            "status": "unresolved",
            "identifiers": {"pmid": pmid},
            "warnings": ["pubmed:no-record"],
        }
    if warnings:
        records[0]["warnings"] = warnings
    return records[0]


def metadata_or_unavailable(client: PaperClient, kind: str, value: str) -> JsonDict:
    if kind in {"pmid", "doi"}:
        return fetch_record(client, kind, value, DEFAULT_INCLUDE)
    return {
        "status": "unresolved",
        "identifiers": {kind: value},
        "warnings": ["no-pmcid"],
    }


def parse_pubmed_xml(xml_text: str, include: set[str]) -> list[JsonDict]:
    if not xml_text.strip():
        return []
    root = ET.fromstring(xml_text)  # noqa: S314 - NCBI/PubMed XML; no defusedxml dependency.
    return [
        parse_pubmed_article(article, include)
        for article in root.findall(".//PubmedArticle")
    ]


def parse_pubmed_article(article: ET.Element, include: set[str]) -> JsonDict:
    medline = article.find("MedlineCitation")
    pubmed_data = article.find("PubmedData")
    article_el = medline.find("Article") if medline is not None else None
    identifiers = parse_pubmed_identifiers(medline, pubmed_data)
    journal = parse_journal(article_el)
    record: JsonDict = {
        "identifiers": identifiers,
        "title": flatten(article_el.find("ArticleTitle"))
        if article_el is not None
        else None,
        "journal": journal,
        "year": journal.get("year"),
        "publication_types": parse_publication_types(article_el),
        "source_urls": source_urls(identifiers),
        "provenance": [
            {"source": "pubmed", "url": pubmed_url(identifiers.get("pmid"))}
        ],
    }
    if "authors" in include:
        record["authors"] = parse_authors(article_el)
    if "abstract" in include:
        abstract = parse_abstract(article_el)
        record["abstract"] = abstract
        record["evidence_level"] = (
            "abstract-only" if abstract.get("text") else "metadata-only"
        )
    else:
        record["evidence_level"] = "metadata-only"
    if "mesh" in include:
        record["mesh"] = parse_mesh(medline)
    if "grants" in include:
        record["grants"] = parse_grants(article_el)
    return record


def parse_pubmed_identifiers(
    medline: ET.Element | None, pubmed_data: ET.Element | None
) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    pmid = text_or_none(medline.find("PMID") if medline is not None else None)
    if pmid:
        identifiers["pmid"] = pmid
    article_id_list = (
        pubmed_data.find("ArticleIdList") if pubmed_data is not None else None
    )
    if article_id_list is None:
        return identifiers
    for article_id in article_id_list.findall("ArticleId"):
        id_type = article_id.attrib.get("IdType")
        value = text_or_none(article_id)
        if not value:
            continue
        if id_type == "doi":
            identifiers["doi"] = value.lower()
        elif id_type == "pmc":
            identifiers["pmcid"] = normalize_pmcid(value)
        elif id_type == "pubmed":
            identifiers.setdefault("pmid", value)
    return identifiers


def parse_journal(article_el: ET.Element | None) -> JsonDict:
    journal_el = article_el.find("Journal") if article_el is not None else None
    issue = journal_el.find("JournalIssue") if journal_el is not None else None
    pub_date = issue.find("PubDate") if issue is not None else None
    year = first_text(pub_date, ("Year", "MedlineDate"))
    return {
        "title": flatten(journal_el.find("Title")) if journal_el is not None else None,
        "iso_abbreviation": flatten(journal_el.find("ISOAbbreviation"))
        if journal_el is not None
        else None,
        "volume": first_text(issue, ("Volume",)),
        "issue": first_text(issue, ("Issue",)),
        "pages": first_text(article_el, ("Pagination/MedlinePgn",))
        if article_el is not None
        else None,
        "year": year[:4] if year else None,
    }


def parse_authors(article_el: ET.Element | None) -> list[JsonDict]:
    author_list = article_el.find("AuthorList") if article_el is not None else None
    if author_list is None:
        return []
    authors: list[JsonDict] = []
    for author in author_list.findall("Author"):
        affiliations = [
            flatten(aff) for aff in author.findall("AffiliationInfo/Affiliation")
        ]
        authors.append(
            {
                "family": first_text(author, ("LastName",)),
                "given": first_text(author, ("ForeName",)),
                "initials": first_text(author, ("Initials",)),
                "collective": first_text(author, ("CollectiveName",)),
                "affiliations": [item for item in affiliations if item],
            }
        )
    return authors


def parse_abstract(article_el: ET.Element | None) -> JsonDict:
    abstract = article_el.find("Abstract") if article_el is not None else None
    sections: list[JsonDict] = []
    if abstract is not None:
        for abstract_text in abstract.findall("AbstractText"):
            text = flatten(abstract_text)
            if text:
                sections.append(
                    {
                        "label": abstract_text.attrib.get("Label"),
                        "nlm_category": abstract_text.attrib.get("NlmCategory"),
                        "text": text,
                    }
                )
    return {
        "text": "\n".join(str(section["text"]) for section in sections),
        "sections": sections,
    }


def parse_publication_types(article_el: ET.Element | None) -> list[str]:
    if article_el is None:
        return []
    return [
        flatten(item)
        for item in article_el.findall("PublicationTypeList/PublicationType")
    ]


def parse_mesh(medline: ET.Element | None) -> list[JsonDict]:
    if medline is None:
        return []
    headings: list[JsonDict] = []
    for heading in medline.findall("MeshHeadingList/MeshHeading"):
        descriptor = heading.find("DescriptorName")
        qualifiers = [
            {
                "name": flatten(item),
                "major_topic": item.attrib.get("MajorTopicYN") == "Y",
            }
            for item in heading.findall("QualifierName")
        ]
        headings.append(
            {
                "descriptor": flatten(descriptor),
                "major_topic": descriptor.attrib.get("MajorTopicYN") == "Y"
                if descriptor is not None
                else False,
                "qualifiers": qualifiers,
            }
        )
    return headings


def parse_grants(article_el: ET.Element | None) -> list[JsonDict]:
    if article_el is None:
        return []
    return [
        {
            "id": first_text(grant, ("GrantID",)),
            "agency": first_text(grant, ("Agency",)),
            "country": first_text(grant, ("Country",)),
            "acronym": first_text(grant, ("Acronym",)),
        }
        for grant in article_el.findall("GrantList/Grant")
    ]


def parse_jats_xml(xml_text: str, wanted_sections: set[str] | None) -> JsonDict:
    if not xml_text.strip():
        return unavailable("pmc:empty-response")
    root = ET.fromstring(xml_text)  # noqa: S314 - NCBI/PMC XML; no defusedxml dependency.
    article = root if strip_ns(root.tag) == "article" else first(root, "article")
    if article is None:
        return unavailable("pmc:no-article")
    identifiers = parse_jats_ids(article)
    sections = parse_body_sections(article)
    if wanted_sections:
        sections = [
            section for section in sections if section.get("type") in wanted_sections
        ]
    figures = parse_captioned(article, "fig")
    tables = parse_captioned(article, "table-wrap")
    references = parse_references(article)
    abstract = parse_jats_abstract(article)
    status = (
        "full-text"
        if sections or figures or tables or references
        else "abstract-only"
        if abstract.get("text")
        else "metadata-only"
    )
    return {
        "identifiers": identifiers,
        "fulltext": {
            "status": status,
            "source": "pmc",
            "license": parse_license(article),
            "abstract": abstract,
            "sections": sections,
            "figures": figures,
            "tables": tables,
            "references": references,
        },
        "evidence_level": status,
        "provenance": [{"source": "pmc-efetch"}],
    }


def parse_jats_ids(article: ET.Element) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    for article_id in find_all(article, "article-id"):
        id_type = article_id.attrib.get("pub-id-type")
        value = flatten(article_id)
        if not value:
            continue
        if id_type == "pmid":
            identifiers["pmid"] = value
        elif id_type == "pmc":
            identifiers["pmcid"] = normalize_pmcid(value)
        elif id_type == "doi":
            identifiers["doi"] = value.lower()
    return identifiers


def parse_jats_abstract(article: ET.Element) -> JsonDict:
    abstract = first(article, "abstract")
    if abstract is None:
        return {"text": "", "sections": []}
    section_nodes = children_named(abstract, "sec")
    sections = [
        {
            "label": child_text(section, "title"),
            "nlm_category": None,
            "text": collect_paragraph_text(section),
        }
        for section in section_nodes
        if collect_paragraph_text(section)
    ]
    if not sections:
        text = collect_paragraph_text(abstract) or flatten(abstract)
        if text:
            sections.append({"label": None, "nlm_category": None, "text": text})
    return {
        "text": "\n".join(str(section["text"]) for section in sections),
        "sections": sections,
    }


def parse_body_sections(article: ET.Element) -> list[JsonDict]:
    body = first(article, "body")
    if body is None:
        return []
    output: list[JsonDict] = []
    order = 0

    def walk(section: ET.Element, path: list[str]) -> None:
        nonlocal order
        title = child_text(section, "title") or "Untitled"
        current_path = [*path, title]
        text = collect_paragraph_text(section)
        if text:
            order += 1
            output.append(
                {
                    "path": current_path,
                    "type": classify_section(current_path),
                    "title": title,
                    "text": text,
                    "order": order,
                }
            )
        for child in children_named(section, "sec"):
            walk(child, current_path)

    for section in children_named(body, "sec"):
        walk(section, [])
    return output


def classify_section(path: Iterable[str]) -> str:
    for title in reversed(list(path)):
        normalized = " ".join(title.lower().split())
        for prefix, section_type in SECTION_TYPES.items():
            if normalized == prefix or normalized.startswith(f"{prefix}:"):
                return section_type
    return "unknown"


def collect_paragraph_text(element: ET.Element) -> str:
    parts = []
    for child in list(element):
        if strip_ns(child.tag) in {"p", "list", "disp-quote"}:
            text = flatten(child)
            if text:
                parts.append(text)
    return "\n".join(parts)


def parse_captioned(article: ET.Element, tag: str) -> list[JsonDict]:
    items = [
        {
            "label": child_text(element, "label"),
            "caption": flatten(first(element, "caption")),
        }
        for element in find_all(article, tag)
    ]
    return [item for item in items if item["label"] or item["caption"]]


def parse_references(article: ET.Element) -> list[JsonDict]:
    refs: list[JsonDict] = []
    for ref in find_all(article, "ref"):
        ids: dict[str, str] = {}
        for pub_id in find_all(ref, "pub-id"):
            id_type = pub_id.attrib.get("pub-id-type")
            value = flatten(pub_id)
            if id_type and value:
                ids[id_type] = value
        refs.append(
            {
                "label": child_text(ref, "label"),
                "text": flatten(ref),
                "identifiers": ids,
            }
        )
    return refs


def parse_license(article: ET.Element) -> JsonDict:
    license_el = first(article, "license")
    if license_el is None:
        return {"type": None, "url": None}
    href = license_el.attrib.get(
        "{http://www.w3.org/1999/xlink}href"
    ) or license_el.attrib.get("href")
    return {"type": license_el.attrib.get("license-type"), "url": href}


def normalize_crossref_work(message: Mapping[str, Any]) -> JsonDict:
    doi_value = message.get("DOI")
    doi = normalize_doi(doi_value) if isinstance(doi_value, str) else None
    authors: list[JsonDict] = []
    raw_authors = message.get("author")
    if isinstance(raw_authors, list):
        authors.extend(
            {
                "family": author.get("family")
                if isinstance(author.get("family"), str)
                else None,
                "given": author.get("given")
                if isinstance(author.get("given"), str)
                else None,
                "collective": None,
            }
            for author in raw_authors
            if isinstance(author, Mapping)
        )
    identifiers = {"doi": doi} if doi else {}
    return {
        "identifiers": identifiers,
        "title": first_string(message.get("title")),
        "journal": {
            "title": first_string(message.get("container-title")),
            "iso_abbreviation": first_string(message.get("short-container-title")),
        },
        "year": crossref_year(message),
        "authors": authors,
        "publisher": message.get("publisher")
        if isinstance(message.get("publisher"), str)
        else None,
        "source_urls": {"doi": f"https://doi.org/{doi}"} if doi else {},
        "provenance": [{"source": "crossref", "url": message.get("URL")}],
        "evidence_level": "metadata-only",
    }


def normalize_idconv(identifier: str, raw: Mapping[str, object]) -> JsonDict:
    records = raw.get("records")
    record = (
        records[0]
        if isinstance(records, list) and records and isinstance(records[0], Mapping)
        else None
    )
    identifiers: dict[str, str] = {}
    warnings: list[str] = []
    status = "unresolved"
    if record is not None:
        for key in ("pmid", "pmcid", "doi"):
            value = record.get(key)
            if isinstance(value, str) and value:
                identifiers[key] = normalize_identifier(key, value)
        status = "resolved" if identifiers else "unresolved"
        error = record.get("errmsg") or record.get("error") or record.get("status")
        if isinstance(error, str) and error.lower() not in {"", "ok"}:
            warnings.append(error)
    else:
        warnings.append("pmc-id-converter:no-record")
    if identifiers and "pmcid" not in identifiers:
        warnings.append("no-pmcid")
    return {
        "input": identifier,
        "identifiers": identifiers,
        "status": status,
        "warnings": warnings,
        "provenance": [{"source": "pmc-id-converter", "url": IDCONV_URL}],
    }


def format_citation(record: JsonDict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(record, indent=2, sort_keys=True)
    if fmt == "markdown":
        return markdown_citation(record)
    if fmt == "bibtex":
        return bibtex(record)
    if fmt == "ris":
        return ris(record)
    msg = f"unsupported citation format: {fmt}"
    raise PaperInputError(msg, exit_code=2)


def markdown_citation(record: JsonDict) -> str:
    year = optional_str(record.get("year")) or "n.d."
    title = optional_str(record.get("title")) or "[missing title]"
    journal = journal_title(record)
    identifiers = identifiers_text(record)
    parts = [f"{author_text(record.get('authors'))} ({year}). {title}."]
    if journal:
        parts.append(f"*{journal}*.")
    if identifiers:
        parts.append(identifiers)
    return " ".join(parts)


def bibtex(record: JsonDict) -> str:
    identifiers = as_dict(record.get("identifiers"))
    authors = author_list(record.get("authors"))
    key = citation_key(
        authors,
        optional_str(record.get("year")),
        identifiers.get("doi") or identifiers.get("pmid") or "ref",
    )
    fields = {
        "title": optional_str(record.get("title")),
        "author": bibtex_authors(authors),
        "journal": journal_title(record),
        "year": optional_str(record.get("year")),
        "doi": identifiers.get("doi"),
        "pmid": identifiers.get("pmid"),
        "pmcid": identifiers.get("pmcid"),
    }
    body = "\n".join(
        f"  {key_name} = {{{escape_bibtex(value)}}},"
        for key_name, value in fields.items()
        if value
    )
    return f"@article{{{key},\n{body}\n}}"


def ris(record: JsonDict) -> str:
    identifiers = as_dict(record.get("identifiers"))
    lines = ["TY  - JOUR"]
    for author in author_list(record.get("authors")):
        rendered = ris_author(author)
        if rendered:
            lines.append(f"AU  - {rendered}")
    append_ris(lines, "TI", optional_str(record.get("title")))
    append_ris(lines, "JO", journal_title(record))
    append_ris(lines, "PY", optional_str(record.get("year")))
    append_ris(lines, "DO", identifiers.get("doi"))
    if identifiers.get("pmid"):
        lines.append(f"AN  - PMID:{identifiers['pmid']}")
    if identifiers.get("pmcid"):
        lines.append(f"AN  - PMCID:{identifiers['pmcid']}")
    lines.append("ER  -")
    return "\n".join(lines)


def strict_validate(record: JsonDict) -> None:
    missing: list[str] = []
    if not record.get("title"):
        missing.append("title")
    if not record.get("year"):
        missing.append("year")
    if not author_list(record.get("authors")):
        missing.append("authors")
    if not journal_title(record):
        missing.append("journal")
    if missing:
        msg = f"missing core citation fields: {', '.join(missing)}"
        raise PaperInputError(msg, exit_code=2)


def print_search(result: JsonDict) -> None:
    print(markdown_heading("PubMed search"))
    print(f"Count: {result.get('count')}")
    print(f"IDs: {', '.join(str(item) for item in as_list(result.get('ids')))}")
    for record in records_from(result):
        print(f"- {record_line(record)}")


def print_fetch(record: JsonDict) -> None:
    print(record_line(record))
    abstract = as_dict(record.get("abstract"))
    if abstract.get("text"):
        print("\n" + markdown_heading("Abstract", level=2))
        print(abstract["text"])


def print_convert(record: JsonDict) -> None:
    print(f"Status: {record.get('status', 'unknown')}")
    for key, value in as_dict(record.get("identifiers")).items():
        print(f"{key.upper()}: {value}")
    warnings = as_list(record.get("warnings"))
    if warnings:
        print("Warnings: " + ", ".join(str(item) for item in warnings))


def print_fulltext(record: JsonDict) -> None:
    fulltext = as_dict(record.get("fulltext"))
    print(f"Status: {fulltext.get('status', 'unavailable')}")
    if fulltext.get("reason"):
        print(f"Reason: {fulltext['reason']}")
    for section in as_list(fulltext.get("sections")):
        if isinstance(section, dict):
            print(
                "\n" + markdown_heading(str(section.get("title", "Untitled")), level=2)
            )
            print(section.get("text", ""))


def print_related(result: JsonDict) -> None:
    if result.get("status") == "unsupported":
        print(f"Unsupported: {result.get('reason')}")
        return
    print(markdown_heading("Related papers"))
    for record in records_from(result):
        print(f"- {record_line(record)}")


def emit(value: JsonDict, *, use_json: bool, printer: Printer) -> None:
    if use_json:
        print_json(value)
    else:
        printer(value)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        msg = "must be positive"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def one_identifier(
    pmid: str | None, pmcid: str | None, doi: str | None
) -> tuple[str, str]:
    present = [("pmid", pmid), ("pmcid", pmcid), ("doi", doi)]
    values = [(key, value) for key, value in present if value]
    if len(values) != 1:
        msg = "provide exactly one identifier"
        raise PaperInputError(msg, exit_code=2)
    key, value = values[0]
    if value is None:
        msg = "provide exactly one identifier"
        raise PaperInputError(msg, exit_code=2)
    return key, normalize_identifier(key, value)


def parse_include(value: str) -> set[str]:
    parsed = {item.strip() for item in value.split(",") if item.strip()}
    unknown = parsed - ALL_INCLUDE
    if unknown:
        msg = f"unknown include fields: {', '.join(sorted(unknown))}"
        raise PaperInputError(msg, exit_code=2)
    return parsed or DEFAULT_INCLUDE


def parse_sections(value: str | None) -> set[str] | None:
    if value is None:
        return None
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def normalize_identifier(kind: str, value: str) -> str:
    if kind == "pmid":
        return normalize_pmid(value)
    if kind == "pmcid":
        return normalize_pmcid(value)
    if kind == "doi":
        return normalize_doi(value)
    msg = f"unsupported identifier type: {kind}"
    raise PaperInputError(msg, exit_code=2)


def normalize_pmid(value: str) -> str:
    stripped = value.strip()
    if not stripped.isdigit():
        msg = f"invalid PMID: {value}"
        raise PaperInputError(msg, exit_code=2)
    return stripped


def normalize_pmcid(value: str) -> str:
    match = re.match(r"^(?:PMC)?(\d+)$", value.strip(), flags=re.IGNORECASE)
    if match is None:
        msg = f"invalid PMCID: {value}"
        raise PaperInputError(msg, exit_code=2)
    return f"PMC{match.group(1)}"


def normalize_doi(value: str) -> str:
    doi = re.sub(
        r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )
    doi = doi.strip().rstrip(".,;)")
    if "/" not in doi or doi.lower().startswith("http"):
        msg = f"invalid DOI: {value}"
        raise PaperInputError(msg, exit_code=2)
    return doi.lower()


def pubmed_query(query: str, paper_type: str | None) -> str:
    if not paper_type:
        return query
    return f"({query}) AND ({paper_type.replace('-', ' ')}[Publication Type])"


def extract_esearch_ids(raw: Mapping[str, object]) -> list[str]:
    esearch = raw.get("esearchresult")
    if not isinstance(esearch, Mapping):
        return []
    ids = esearch.get("idlist")
    if not isinstance(ids, list):
        return []
    return [str(item) for item in ids if str(item).isdigit()]


def parse_elink_ids(raw: Mapping[str, object]) -> list[str]:
    ids: list[str] = []
    linksets = raw.get("linksets")
    if not isinstance(linksets, list):
        return ids
    for linkset in linksets:
        if not isinstance(linkset, Mapping):
            continue
        dbs = linkset.get("linksetdbs")
        if not isinstance(dbs, list):
            continue
        for db in dbs:
            if not isinstance(db, Mapping):
                continue
            links = db.get("links")
            if isinstance(links, list):
                ids.extend(str(item) for item in links if str(item).isdigit())
    return ids


def source_urls(identifiers: Mapping[str, str]) -> dict[str, str]:
    urls: dict[str, str] = {}
    if identifiers.get("pmid"):
        urls["pubmed"] = pubmed_url(identifiers["pmid"])
    if identifiers.get("pmcid"):
        urls["pmc"] = f"https://pmc.ncbi.nlm.nih.gov/articles/{identifiers['pmcid']}/"
    if identifiers.get("doi"):
        urls["doi"] = (
            f"https://doi.org/{urllib.parse.quote(identifiers['doi'], safe='/')}"
        )
    return urls


def pubmed_url(pmid: str | None) -> str:
    return (
        f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        if pmid
        else "https://pubmed.ncbi.nlm.nih.gov/"
    )


def flatten(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def text_or_none(element: ET.Element | None) -> str | None:
    text = flatten(element)
    return text or None


def first_text(element: ET.Element | None, paths: Sequence[str]) -> str | None:
    if element is None:
        return None
    for path in paths:
        text = text_or_none(element.find(path))
        if text:
            return text
    return None


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find_all(element: ET.Element, name: str) -> list[ET.Element]:
    return [
        candidate for candidate in element.iter() if strip_ns(candidate.tag) == name
    ]


def first(element: ET.Element, name: str) -> ET.Element | None:
    for candidate in element.iter():
        if strip_ns(candidate.tag) == name:
            return candidate
    return None


def children_named(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if strip_ns(child.tag) == name]


def child_text(element: ET.Element, name: str) -> str | None:
    for child in list(element):
        if strip_ns(child.tag) == name:
            return text_or_none(child)
    return None


def first_string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return None


def crossref_year(message: Mapping[str, Any]) -> str | None:
    for key in ("issued", "published-online", "published-print"):
        value = message.get(key)
        if not isinstance(value, Mapping):
            continue
        parts = value.get("date-parts")
        if (
            isinstance(parts, list)
            and parts
            and isinstance(parts[0], list)
            and parts[0]
        ):
            year = parts[0][0]
            if isinstance(year, int):
                return str(year)
    return None


def user_agent(config: Config) -> str:
    return (
        f"{TOOL_NAME}/0.1 (mailto:{config.email})"
        if config.email
        else f"{TOOL_NAME}/0.1"
    )


def rate_limited_payload(exc: RateLimitError) -> JsonDict:
    return {
        "status": "rate-limited",
        "error": "rate-limited",
        "message": exc.safe_message,
        "retry_after_seconds": exc.retry_after_seconds,
        "retryable": True,
    }


def unsupported(command: str, mode: str, reason: str) -> JsonDict:
    return {"status": "unsupported", "command": command, "mode": mode, "reason": reason}


def europepmc_unavailable(kind: str, value: str) -> JsonDict:
    return {
        "identifiers": {kind: value},
        "fulltext": {
            "status": "unavailable",
            "reason": "europepmc-fulltextxml-not-implemented",
            "tried": [{"source": "europepmc", "status": "unsupported"}],
        },
        "evidence_level": "unavailable",
    }


def unavailable(reason: str) -> JsonDict:
    return {
        "fulltext": {
            "status": "unavailable",
            "reason": reason,
            "tried": [{"source": "pmc", "status": reason}],
        },
        "evidence_level": "unavailable",
    }


def strict_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def optional_str(value: object) -> str | None:
    return strict_string(value)


def as_dict(value: object) -> JsonDict:
    return dict(value) if isinstance(value, Mapping) else {}


def as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def records_from(result: JsonDict) -> list[JsonDict]:
    records = result.get("records")
    return (
        [dict(item) for item in records if isinstance(item, Mapping)]
        if isinstance(records, list)
        else []
    )


def record_line(record: JsonDict) -> str:
    title = optional_str(record.get("title")) or "[missing title]"
    year = optional_str(record.get("year")) or "n.d."
    identifiers = as_dict(record.get("identifiers"))
    suffix = []
    if identifiers.get("pmid"):
        suffix.append(f"PMID {identifiers['pmid']}")
    if identifiers.get("doi"):
        suffix.append(f"DOI {identifiers['doi']}")
    return f"{title} ({year})" + (f" — {'; '.join(suffix)}" if suffix else "")


def author_list(value: object) -> list[JsonDict]:
    return (
        [dict(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, list)
        else []
    )


def author_text(value: object) -> str:
    authors = author_list(value)
    if not authors:
        return "[missing authors]"
    names = [display_author(author) for author in authors[:3]]
    names = [name for name in names if name]
    if len(authors) > 3:
        names.append("et al.")
    return ", ".join(names) if names else "[missing authors]"


def display_author(author: Mapping[str, object]) -> str:
    collective = optional_str(author.get("collective"))
    if collective:
        return collective
    return " ".join(
        part
        for part in (
            optional_str(author.get("given")),
            optional_str(author.get("family")),
        )
        if part
    )


def bibtex_authors(authors: list[JsonDict]) -> str | None:
    names: list[str] = []
    for author in authors:
        collective = optional_str(author.get("collective"))
        if collective:
            names.append(f"{{{collective}}}")
            continue
        family = optional_str(author.get("family"))
        given = optional_str(author.get("given"))
        if family and given:
            names.append(f"{family}, {given}")
        elif family:
            names.append(family)
    return " and ".join(names) if names else None


def ris_author(author: Mapping[str, object]) -> str | None:
    collective = optional_str(author.get("collective"))
    if collective:
        return collective
    family = optional_str(author.get("family"))
    given = optional_str(author.get("given"))
    if family and given:
        return f"{family}, {given}"
    return family


def journal_title(record: JsonDict) -> str | None:
    journal = record.get("journal")
    if not isinstance(journal, Mapping):
        return None
    return optional_str(journal.get("title")) or optional_str(
        journal.get("iso_abbreviation")
    )


def identifiers_text(record: JsonDict) -> str:
    identifiers = as_dict(record.get("identifiers"))
    parts = [
        f"{key.upper()}: {identifiers[key]}"
        for key in ("doi", "pmid", "pmcid")
        if identifiers.get(key)
    ]
    return "; ".join(parts)


def append_ris(lines: list[str], tag: str, value: str | None) -> None:
    if value:
        lines.append(f"{tag}  - {value}")


def escape_bibtex(value: str) -> str:
    return re.sub(r"([{}])", r"\\\1", value)


def citation_key(authors: list[JsonDict], year: str | None, fallback: object) -> str:
    first = "work"
    if authors:
        first = (
            optional_str(authors[0].get("family"))
            or optional_str(authors[0].get("collective"))
            or first
        )
    safe_first = re.sub(r"[^A-Za-z0-9]+", "", first) or "work"
    safe_year = re.sub(r"[^0-9]+", "", year or "") or "nd"
    safe_fallback = re.sub(r"[^A-Za-z0-9]+", "", str(fallback))[-6:] or "ref"
    return f"{safe_first}{safe_year}{safe_fallback}"
