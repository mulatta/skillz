# Full-text fallback API reference

Purpose: retrieve legal open-access full text for `biorefs-cli paper fulltext`. Never use Sci-Hub, shadow libraries, credential sharing, paywall scraping, or local PDF extraction. OpenAlex and Unpaywall are discovery aids; they are not full-text stores. Current CLI full-text support is PMC-first through PMCID conversion and PMC EFetch; other sources below are reference notes for legal fallback expansion.

## Contents

- [Resolution algorithm](#resolution-algorithm)
- [PMC EFetch](#pmc-efetch)
- [PMC ID Converter](#pmc-id-converter)
- [Europe PMC](#europe-pmc)
- [bioRxiv and medRxiv](#biorxiv-and-medrxiv)
- [OpenAlex OA discovery fields](#openalex-oa-discovery-fields)
- [Optional Unpaywall DOI resolver](#optional-unpaywall-doi-resolver)
- [Publisher OA landing pages](#publisher-oa-landing-pages)
- [Parsing expectations](#parsing-expectations)
- [Structured unavailable output](#structured-unavailable-output)

## Resolution algorithm

Input may include `pmcid`, `pmid`, `doi`, or preprint server DOI. Normalize identifiers first:

- PMCID: uppercase `PMC` prefix, no URL wrapper.
- PMID: digits only.
- DOI: lowercase, strip `https://doi.org/`, keep slash path.
- OpenAlex Work ID: use only to obtain DOI/PMID/PMCID and OA location hints.

Try tiers in this order and stop at first tier that returns parseable, legal full text:

1. **PMC EFetch direct PMCID**
   - If input has PMCID, fetch PMC article XML with NCBI EFetch.
   - Stop when response contains parseable JATS article body or back matter.
1. **PMC ID Converter, then PMC EFetch**
   - If input has PMID or DOI, convert to PMCID.
   - If PMCID found, fetch through PMC EFetch.
   - Stop on parseable JATS.
1. **Europe PMC fullTextXML**
   - Search by PMCID, PMID, DOI, or title metadata.
   - Prefer records with source `PMC` and full-text availability.
   - Fetch `/PMC.../fullTextXML` for OA subset.
   - Stop on parseable full-text XML.
1. **OpenAlex OA locations**
   - Fetch Work by DOI, PMID, PMCID, or OpenAlex ID.
   - Inspect `best_oa_location`, `locations`, and `open_access`.
   - Do not treat OpenAlex as content. Use only explicit OA landing-page URLs as candidates for later tiers.
1. **bioRxiv/medRxiv preprints**
   - If DOI/server indicates bioRxiv or medRxiv, query server API metadata.
   - Prefer JATS/XML full text when link is explicit.
   - Stop when parseable structured full text exists.
1. **Optional Unpaywall DOI resolver**
   - Use only when configured `email` exists and DOI exists.
   - Inspect OA locations; add explicit OA URLs to publisher/repository candidates.
1. **Publisher OA landing page**
   - Follow only explicit OA URLs from source metadata, OpenAlex, Europe PMC, Unpaywall, Crossref license links, or preprint metadata.
   - Stop on parseable HTML article or JATS XML with clear OA/license markers.

If no tier succeeds, return `status: unavailable` with structured `reason` and `tried` outcomes. Do not silently return abstract text as full text.

## Stop conditions

Stop with `status: available` only when fetched content includes one of:

- JATS/XML article with `<body>`, `<sec>`, `<p>`, tables, figures, or references.
- Europe PMC `fullTextXML` OA article XML.
- bioRxiv/medRxiv JATS/XML.
- Publisher/repository article HTML or JATS/XML with clear OA/license/access markers.

Return `status: abstract-only` when metadata and abstract exist but no legal full text exists. This must be distinct from `available` and `unavailable`.

## PMC EFetch

Role: primary structured full-text source for PMCID records.

Endpoint pattern:

```text
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=PMC_ID&retmode=xml
```

Inputs:

- `id`: PMCID with or without `PMC` prefix may work; store canonical `PMC1234567`.
- `db=pmc`.
- `retmode=xml`.
- `tool`, `email`, and optional `api_key` for NCBI policy/rate limits.

Expected output:

- NLM/JATS-like XML with `<article>`, `<front>`, `<body>`, `<back>`.
- Article IDs in `<article-id pub-id-type="pmid|pmc|doi">`.
- Full text sections under `<body>` when available.

Failure outcomes:

- `pmc:miss` when PMCID absent or EFetch returns no article.
- `pmc:not-oa` when record exists but no accessible OA XML/full body is returned.
- `pmc:parse-error` when XML is malformed or has no usable article text.
- `pmc:http-429`, `pmc:http-5xx`, `pmc:timeout` for transient errors after retries.

## PMC ID Converter

Role: map PMID/DOI to PMCID before PMC EFetch.

Endpoint pattern:

```text
https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids=ID1,ID2&format=json&tool=biorefs-cli&email=EMAIL
```

Inputs:

- `ids`: PMID, PMCID, DOI, or comma-separated batch.
- `format=json` for stable parsing.
- `tool`, `email`; optional NCBI API key when supported by client policy.

Expected output fields:

- `records[].pmcid`
- `records[].pmid`
- `records[].doi`
- `records[].versions[]` for versioned PMC records when present.
- `records[].status` or error fields for unresolved IDs.

Use:

1. Convert PMID/DOI to PMCID.
1. If `pmcid` exists, continue to PMC EFetch.
1. If no PMCID exists, record `pmcid-converter:no-pmcid` and continue to Europe PMC.

## Europe PMC

Base URL:

```text
https://www.ebi.ac.uk/europepmc/webservices/rest
```

Role: biomedical metadata search plus OA full-text XML fallback.

### Search endpoint

```text
GET /search?query=QUERY&resultType=core&format=json&pageSize=25&cursorMark=*
POST /searchPOST
```

Useful exact-ID queries:

```text
ext_id:PMID src:MED
ext_id:PMC1234567 src:PMC
DOI:"10.xxxx/yyyy"
```

Source types:

- `MED`: PubMed/MEDLINE-style records, often abstract/metadata only.
- `PMC`: full-text PMC records; preferred for `/fullTextXML`.
- `PPR`: preprints in Europe PMC, useful for bioRxiv/medRxiv discovery.

Important parameters:

- `resultType=core`: full metadata, abstracts, full-text links, MeSH when available.
- `format=json`: parse metadata.
- `pageSize`: 1-1000.
- `cursorMark`: start with `*`; continue with `nextCursorMark` for multi-page searches.
- `email`: optional EBI contact parameter.

Cursor pagination is useful for search commands and broad fallbacks. For exact DOI/PMID/PMCID lookup, one page is usually enough.

### Article metadata endpoint

```text
GET /article/{source}/{id}?resultType=core&format=json
```

Use when search returns `source` and `id`; inspect metadata/full-text link hints before fetching XML.

### Full-text XML endpoint

```text
GET /{id}/fullTextXML
```

`id` must be an external full-text ID starting with `PMC`, for example `PMC3257301`. Endpoint returns XML only for Europe PMC OA full-text subset.

Expected outcomes:

- `europepmc:hit` when search finds matching record.
- `europepmc:fulltextxml:hit` when `/fullTextXML` returns parseable XML.
- `europepmc:abstract-only` when record has abstract but no OA full text.
- `europepmc:no-fulltextxml` when record has no OA XML endpoint/content.
- `europepmc:source-med-only` when only `MED` record exists.
- `europepmc:source-ppr` when preprint record should be passed to preprint tier.

## bioRxiv and medRxiv

Role: preprint metadata and legal full-text fallback for server-hosted public preprints.

Base API pattern:

```text
https://api.biorxiv.org/details/{server}/{interval}
https://api.biorxiv.org/details/{server}/{interval}/{cursor}
```

Where:

- `server`: `biorxiv` or `medrxiv`.
- `interval`: `YYYY-MM-DD/YYYY-MM-DD`, `YYYY-MM-DD`, or server-supported date window.
- `cursor`: numeric offset for pagination.

DOI lookup pattern:

```text
https://api.biorxiv.org/details/{server}/{doi}/na/json
```

Metadata fields commonly used:

- `doi`
- `title`
- `authors`
- `author_corresponding`
- `author_corresponding_institution`
- `date`
- `version`
- `type`
- `license`
- `category`
- `abstract`
- `published` / `published_journal` when matched to final article

Full-text link patterns:

- Landing page: `https://www.biorxiv.org/content/{doi}v{version}` or `https://www.medrxiv.org/content/{doi}v{version}`.
- JATS/XML: append `.source.xml` or use explicit XML/JATS links discovered from landing page metadata when available.

Do not infer support for local or fetched PDF parsing from preprint metadata. Keep PDF URLs as source metadata unless a later implementation explicitly adds legal PDF handling.

Outcomes:

- `preprint:jats:hit`
- `preprint:metadata-only`
- `preprint:not-preprint-doi`
- `preprint:no-oa-file`

## OpenAlex OA discovery fields

Endpoint:

```text
GET https://api.openalex.org/works/{id}
```

`id` may be OpenAlex Work ID, DOI URL, `doi:...`, `pmid:...`, or `pmcid:...` depending on client normalization.

Use these Work fields only as discovery aids:

- `ids.doi`, `ids.pmid`, `ids.pmcid`: identifier normalization.
- `open_access.is_oa`: whether OpenAlex thinks work is OA.
- `open_access.oa_status`: `diamond`, `gold`, `hybrid`, `bronze`, `green`, or `closed`.
- `open_access.oa_url`: best OA URL hint.
- `open_access.any_repository_has_fulltext`: repository full-text hint.
- `best_oa_location`: preferred OA `Location`.
- `locations[]`: all known hosting locations.

Location fields:

- `is_oa`: require `true` before using URL as OA candidate.
- `landing_page_url`: candidate article/repository landing page.
- `pdf_url`: candidate direct PDF metadata; current CLI does not fetch PDFs.
- `license` / `license_id`: OA license, e.g. `cc-by`.
- `version`: `publishedVersion`, `acceptedVersion`, or `submittedVersion`.
- `is_accepted`, `is_published`: version hints.
- `source`: source metadata for publisher/repository.

Never report OpenAlex abstract reconstruction as full text. OpenAlex abstracts are metadata only and may be represented as an inverted index.

Outcomes:

- `openalex:oa-location` when explicit OA candidate URL exists.
- `openalex:no_oa_location` when `is_oa` false or no usable URL.
- `openalex:closed` when `open_access.oa_status=closed`.
- `openalex:metadata-only` when identifiers found but no OA content candidate.

## Optional Unpaywall DOI resolver

Use only when DOI exists and configured `email` is available.

Endpoint pattern:

```text
https://api.unpaywall.org/v2/{doi}?email={configured-email}
```

Use as DOI OA discovery, not as content store. Inspect:

- `is_oa`
- `oa_status`
- `best_oa_location`
- `oa_locations[]`
- `url_for_landing_page`
- `url_for_pdf` (metadata only unless PDF handling is explicitly implemented)
- `license`
- `host_type`
- `version`

Only follow URLs from OA locations. Record `unpaywall:disabled` when email missing; do not fail overall resolution because Unpaywall is optional.

## Publisher OA landing pages

Use publisher/repository URLs only when evidence indicates legal OA:

- URL came from PMC/Europe PMC/OpenAlex/Unpaywall/Crossref license/preprint metadata as OA.
- Page or metadata shows Creative Commons/open license or explicit free full text.

Do not:

- Circumvent paywalls, robots, referrer checks, session gates, CAPTCHAs, or institutional auth.
- Scrape pages that expose abstract only while full text is gated.

Prefer structured formats in this order:

1. JATS/XML from explicit link.
1. Semantic HTML article body with license marker.

Publisher outcomes:

- `publisher:jats:hit`
- `publisher:html:hit`
- `publisher:abstract-only`
- `publisher:license-missing`
- `publisher:paywalled`
- `publisher:blocked`

## Parsing expectations

For XML/JATS, extract structured evidence with source provenance:

- Title: `front/article-meta/title-group/article-title`.
- Abstract: `front/article-meta/abstract`.
- Body: `body/sec`, recursive nested sections, `title`, `p`, lists.
- Sections: preserve hierarchy and labels where present.
- Tables: `table-wrap`, `label`, `caption`, `table`; keep rows/cells when possible.
- Figures: `fig`, `label`, `caption`, `graphic` links if present.
- References: `back/ref-list/ref`, citation identifiers, titles, authors, year, DOI/PMID/PMCID.
- Supplementary material: record links/labels; fetch only legal OA files when requested.

For HTML, require article-body selectors plus OA/license marker. Preserve section headings and provenance URL.

Evidence classification:

- `full-text`: text from body/sections/tables/figures/references.
- `abstract-only`: title/abstract/metadata only.
- `metadata-only`: no abstract or body.

## Structured unavailable output

Return stable JSON for failures and partial successes.

Unavailable example:

```json
{
  "status": "unavailable",
  "reason": "no-oa",
  "evidence_level": "metadata-only",
  "identifiers": {
    "pmid": "12345678",
    "doi": "10.1234/example"
  },
  "tried": [
    {"tier": "pmc", "outcome": "miss"},
    {"tier": "pmcid-converter", "outcome": "no-pmcid"},
    {"tier": "europepmc", "outcome": "abstract-only"},
    {"tier": "openalex", "outcome": "no_oa_location"},
    {"tier": "preprint", "outcome": "not-preprint-doi"},
    {"tier": "unpaywall", "outcome": "disabled"},
    {"tier": "publisher", "outcome": "license-missing"}
  ]
}
```

Available example:

```json
{
  "status": "available",
  "evidence_level": "full-text",
  "source": "pmc-efetch",
  "format": "jats-xml",
  "license": "unknown-from-source",
  "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
  "tried": [
    {"tier": "pmc", "outcome": "hit", "pmcid": "PMC1234567"}
  ]
}
```

Recommended top-level `reason` values:

- `no-identifier`
- `no-pmcid`
- `no-oa`
- `abstract-only`
- `metadata-only`
- `license-missing`
- `paywalled`
- `blocked`
- `parse-error`
- `timeout`
- `rate-limited`
- `network-error`

Each `tried` item should include `tier`, `outcome`, optional `url`, optional `status_code`, optional `identifier`, and optional `detail` without secrets.

## HTTP/client behavior

Use bounded requests, source-specific rate limits, and synchronous CLI UX.

Implementation expectations for future code:

- Global and per-host concurrency limits.
- Retries with exponential backoff and jitter for 429/5xx/timeouts.
- Short connect timeout and bounded read timeout.
- Respect `Retry-After`.
- Cache successful metadata, ID conversion, OA location discovery, and fetched full-text artifacts under XDG cache paths.
- Cache negative `no-oa` results with shorter TTL than successes.
- Include contact email parameters where APIs support them.
- Never log API keys, emails from secret stores, cookies, or authorization headers.

## Source docs

- NCBI E-utilities help: https://www.ncbi.nlm.nih.gov/books/NBK25499/
- NCBI EFetch: https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.EFetch
- PMC ID Converter: https://www.ncbi.nlm.nih.gov/pmc/tools/id-converter-api/
- PMC OA services: https://www.ncbi.nlm.nih.gov/pmc/tools/oa-service/
- Europe PMC REST API: https://europepmc.org/RestfulWebService
- Europe PMC Swagger source used here: https://www.ebi.ac.uk/europepmc/webservices/api/swagger.json
- OpenAlex Works API: https://docs.openalex.org/api-entities/works
- OpenAlex OpenAPI source used here: https://docs.openalex.org/api-reference/openapi.json
- bioRxiv/medRxiv API: https://api.biorxiv.org/
- bioRxiv content pages: https://www.biorxiv.org/
- medRxiv content pages: https://www.medrxiv.org/
- Unpaywall API: https://unpaywall.org/products/api
- JATS Archiving and Interchange Tag Set: https://jats.nlm.nih.gov/archiving/
