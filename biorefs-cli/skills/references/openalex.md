# OpenAlex reference for biorefs-cli

OpenAlex indexes scholarly metadata and links. Use it for identifier mapping, open-access location discovery, citation/reference graph enrichment, related works, and landscape summaries. Do not treat OpenAlex as a full-text store.

Legal full text must come from PMC, Europe PMC, bioRxiv/medRxiv, publisher OA links, or OA locations discovered through OpenAlex and fetched according to source terms.

## Contents

- [Endpoint, auth, and etiquette](#endpoint-auth-and-etiquette)
- [Work lookup by identifier](#work-lookup-by-identifier)
- [Works search](#works-search)
- [Abstract reconstruction](#abstract-reconstruction)
- [Key work fields for biorefs](#key-work-fields-for-biorefs)
- [OA discovery](#oa-discovery)
- [Citation graph patterns](#citation-graph-patterns)
- [Trend and group-by patterns](#trend-and-group-by-patterns)
- [Expected normalized output](#expected-normalized-output)

## Endpoint, auth, and etiquette

- Base URL: `https://api.openalex.org`
- Main biorefs endpoint: `GET /works` and `GET /works/{id}`
- Auth: no API key required for biorefs use.
- Polite pool: include `mailto=` on every request when `OPENALEX_EMAIL` or configured email exists.

Example:

```text
https://api.openalex.org/works/doi:10.1158%2F2159-8290.cd-12-0049?mailto=<configured-email>
```

Operational rules:

- Never send fake email. Omit `mailto` if no configured email exists.
- Keep bounded concurrency and client-side rate limiting. Stay below OpenAlex public limits; default to conservative throughput.
- Use retries with exponential backoff for `429`, `500`, `502`, `503`, `504`.
- Respect `Retry-After` when present.
- Set connect/read timeouts.
- Cache GET responses under XDG cache paths.
- CLI remains synchronous; internals may use async HTTP.

## Work lookup by identifier

Use `GET /works/{id}` for one work. Normalize user IDs before request.

Accepted ID forms for biorefs:

| Input | Normalize to request ID | Notes |
| --- | --- | --- |
| `W2741809807` | `W2741809807` | OpenAlex work ID short form |
| `https://openalex.org/W2741809807` | `W2741809807` | Strip URL prefix |
| `openalex:W2741809807` | `W2741809807` | Strip local prefix |
| `10.1158/2159-8290.CD-12-0049` | `doi:10.1158/2159-8290.cd-12-0049` | Lowercase DOI; URL-encode slash in path |
| `https://doi.org/10.1158/2159-8290.CD-12-0049` | `doi:10.1158/2159-8290.cd-12-0049` | Strip DOI resolver |
| `doi:10.1158/2159-8290.CD-12-0049` | `doi:10.1158/2159-8290.cd-12-0049` | Preserve DOI punctuation |
| `23103855` with `--pmid` | `pmid:23103855` | PMID is numeric but only normalize as PMID when context says PMID |
| `PMID:23103855` | `pmid:23103855` | Strip prefix |
| `https://pubmed.ncbi.nlm.nih.gov/23103855/` | `pmid:23103855` | Strip URL |
| `PMC3525065` | `pmcid:PMC3525065` | Preserve `PMC` prefix |
| `pmcid:pmc3525065` | `pmcid:PMC3525065` | Uppercase `PMC` |

URL-encode path IDs with reserved characters. DOI slash must not create accidental route segments in clients that do not support wildcard path params:

```text
GET /works/doi:10.1158%2F2159-8290.cd-12-0049?mailto=<configured-email>
GET /works/pmid:23103855?mailto=<configured-email>
GET /works/pmcid:PMC3525065?mailto=<configured-email>
GET /works/W2741809807?mailto=<configured-email>
```

Use `select=` for lookup when only enrichment fields are needed:

```text
GET /works/doi:10.1158%2F2159-8290.cd-12-0049?select=id,doi,ids,title,publication_year,authorships,primary_location,best_oa_location,locations,open_access,referenced_works,referenced_works_count,cited_by_count,related_works,topics,primary_topic,abstract_inverted_index&mailto=<configured-email>
```

## Works search

Use `GET /works` for search and lists.

Common parameters:

- `search=` full-text search over titles, abstracts, and indexed text.
- `filter=` comma-separated filters. Commas mean AND. Use documented filter values for OR where supported.
- `select=` comma-separated fields to reduce payload.
- `sort=` field sort. Use `-field` for descending per OpenAPI spec.
- `per_page=` max 100.
- `page=` shallow pagination only.
- `cursor=` deep pagination. Start with `cursor=*`, then continue with response `meta.next_cursor`.
- `group_by=` aggregate buckets instead of full work records.

Examples:

```text
# Search recent biomedical papers, payload kept small
GET /works?search=BRCA1%20PARP%20inhibitor%20resistance&filter=type:article,publication_year:>2010&select=id,doi,ids,title,publication_year,cited_by_count,open_access,primary_location,best_oa_location&sort=-cited_by_count&per_page=25&mailto=<configured-email>

# Find OA works with repository or publisher locations
GET /works?filter=open_access.is_oa:true,type:article&search=CRISPR%20base%20editing&select=id,doi,title,open_access,best_oa_location,locations&per_page=50&mailto=<configured-email>

# Cursor paging
GET /works?search=single-cell%20atlas&filter=publication_year:2024&per_page=100&cursor=*&mailto=<configured-email>
```

Search and filter patterns useful to biorefs:

```text
search=<query>
filter=doi:10.1158/2159-8290.cd-12-0049
filter=pmid:23103855
filter=pmcid:PMC3525065
filter=open_access.is_oa:true
filter=open_access.oa_status:gold
filter=type:article
filter=publication_year:2024
filter=publication_year:>2020
filter=cited_by_count:>100
filter=authorships.institutions.country_code:KR
filter=author.id:A5023888391
filter=institutions.id:I27837315
```

For CLI output, cap results by requested `--limit`. For large list collection, use cursor pagination and stop when enough normalized records are collected.

## Abstract reconstruction

OpenAlex does not return plaintext abstracts. Some works include `abstract_inverted_index`, mapping each word to positions.

Reconstruction algorithm:

1. If `abstract_inverted_index` is null or missing, report `abstract.status = "unavailable"` and reason `no-abstract`.
1. Allocate tokens up to max position.
1. For each `word -> [positions]`, place `word` at each position.
1. Join tokens with spaces.
1. Mark provenance as `openalex.abstract_inverted_index`.

Example:

```json
{
  "abstract_inverted_index": {
    "BRCA1": [0],
    "loss": [1],
    "confers": [2],
    "resistance": [3]
  }
}
```

Reconstructed text:

```text
BRCA1 loss confers resistance
```

Do not infer missing words. If position gaps exist, preserve known tokens and mark abstract as partial.

## Key work fields for biorefs

Fetch these fields for paper enrichment:

| Field | Use |
| --- | --- |
| `id` | Canonical OpenAlex URL, e.g. `https://openalex.org/W...` |
| `doi` | Canonical DOI URL when known |
| `ids` | External IDs: `openalex`, `doi`, `pmid`, `pmcid`, `mag` |
| `title` / `display_name` | Work title |
| `publication_year`, `publication_date` | Date metadata |
| `authorships` | Authors, positions, corresponding flag, institutions, countries, raw affiliations |
| `primary_location` | Version-of-record or closest primary host |
| `best_oa_location` | Best OA host selected by OpenAlex |
| `locations` | All known locations with source, landing page, PDF URL, license, version |
| `open_access` | `is_oa`, `oa_status`, `oa_url`, repository full-text flag |
| `referenced_works` | OpenAlex IDs cited by this work |
| `referenced_works_count` | Count of references |
| `cited_by_count` | Citation count |
| `related_works` | Algorithmically related OpenAlex work IDs |
| `topics`, `primary_topic` | Current topic taxonomy with scores and hierarchy |
| `concepts` | Legacy taxonomy if present in older responses; prefer topics |
| `primary_location.source`, `locations[].source` | Source metadata: source ID, name, ISSN-L/ISSN, OA/source type, host organization |
| `abstract_inverted_index` | Abstract reconstruction input |
| `is_retracted`, `is_paratext` | Quality flags |

Source/location subfields to preserve:

```text
location.is_oa
location.landing_page_url
location.pdf_url
location.license
location.license_id
location.version
location.is_accepted
location.is_published
location.source.id
location.source.display_name
location.source.issn_l
location.source.issn
location.source.is_oa
location.source.is_in_doaj
location.source.type
location.source.host_organization_name
```

## OA discovery

Use OpenAlex to discover legal OA candidates, not to fetch full text directly.

Discovery order:

1. `open_access.oa_url` if present.
1. `best_oa_location` when `is_oa=true`.
1. `locations[]` where `is_oa=true`, preferring `pdf_url` for PDF retrieval and `landing_page_url` for source landing pages.
1. Cross-check PMCID with PMC and Europe PMC before publisher/repository scraping.

Return source transparency for every OA candidate:

```json
{
  "url": "https://example.org/article.pdf",
  "url_type": "pdf",
  "is_oa": true,
  "license": "cc-by",
  "version": "publishedVersion",
  "source": {
    "id": "https://openalex.org/S...",
    "display_name": "Journal name",
    "type": "journal",
    "is_in_doaj": true
  },
  "provenance": "openalex.locations"
}
```

Limitations:

- `oa_status=bronze` may be free-to-read without reusable license.
- `license` can be null or stale.
- `pdf_url` can be missing, blocked, stale, or point to a landing page.
- Repository versions can be `acceptedVersion` or `submittedVersion`, not version of record.
- Publisher access can change after indexing.
- OpenAlex metadata does not prove text-mining rights. Preserve license and source fields.

Unavailable examples:

```json
{"status":"unavailable","reason":"no-oa","tried":["openalex:open_access.is_oa=false"]}
{"status":"unavailable","reason":"no-pdf-url","tried":["openalex:oa_location_without_pdf"]}
{"status":"unavailable","reason":"fulltext-not-in-openalex","tried":["openalex:metadata_only"]}
```

## Citation graph patterns

`biorefs-cli openalex graph --direction references|cited-by|related` should normalize input ID once, then use graph-specific patterns.

### References

1. Fetch target work with `referenced_works` and `referenced_works_count`.
1. Return `referenced_works` as edges immediately.
1. If metadata is requested, fetch referenced OpenAlex IDs with bounded concurrency using `GET /works/{WID}` and `select=`.
1. Preserve target order from `referenced_works`.

Edge shape:

```json
{"source":"W_TARGET","target":"W_REFERENCE","direction":"references","provenance":"openalex.referenced_works"}
```

### Cited by

Use the `cites:` filter to list works that cite the target:

```text
GET /works?filter=cites:W2741809807&select=id,doi,ids,title,publication_year,cited_by_count,authorships,primary_location,best_oa_location,open_access&sort=-cited_by_count&per_page=50&mailto=<configured-email>
```

For newest citing papers:

```text
GET /works?filter=cites:W2741809807&sort=-publication_date&per_page=50&mailto=<configured-email>
```

Edge shape:

```json
{"source":"W_CITING","target":"W_TARGET","direction":"cited-by","provenance":"openalex.filter.cites"}
```

### Related

1. Fetch target work with `related_works`.
1. Fetch related IDs with bounded concurrency.
1. Return relation type as algorithmic similarity, not citation evidence.

```json
{"source":"W_TARGET","target":"W_RELATED","direction":"related","provenance":"openalex.related_works","evidence":"algorithmic"}
```

Graph output should include:

- `query` normalized input IDs.
- `nodes` normalized work records.
- `edges` with provenance and direction.
- `truncated=true` when `--limit` stops traversal.
- `unavailable` entries for IDs that fail lookup.

## Trend and group-by patterns

Use `group_by=` for research landscape summaries. MVP focuses paper enrichment, so trend commands are secondary.

Examples:

```text
# Publications by year for query
GET /works?search=spatial%20transcriptomics&filter=type:article&group_by=publication_year&mailto=<configured-email>

# OA status distribution
GET /works?search=single-cell%20RNA-seq&filter=publication_year:>2018&group_by=open_access.oa_status&mailto=<configured-email>

# Countries contributing to topic/query
GET /works?search=CAR-T%20therapy&filter=publication_year:>2020&group_by=authorships.institutions.country_code&mailto=<configured-email>

# Topic landscape
GET /works?search=CRISPR%20base%20editing&group_by=primary_topic.id&mailto=<configured-email>
```

Trend outputs should report query, filters, bucket key, display name when available, count, and source URL. Avoid causal claims from counts alone.

## Expected normalized output

Work enrichment record:

```json
{
  "source": "openalex",
  "openalex_id": "W2741809807",
  "openalex_url": "https://openalex.org/W2741809807",
  "doi": "10.7717/peerj.4375",
  "doi_url": "https://doi.org/10.7717/peerj.4375",
  "pmid": "29456894",
  "pmcid": "PMC5828010",
  "title": "Work title",
  "publication_year": 2018,
  "publication_date": "2018-02-13",
  "authors": [
    {
      "name": "Author Name",
      "openalex_id": "A...",
      "orcid": "https://orcid.org/0000-0000-0000-0000",
      "position": "first",
      "is_corresponding": false,
      "institutions": [
        {"openalex_id":"I...","name":"Institution","ror":"https://ror.org/...","country_code":"US"}
      ]
    }
  ],
  "source_metadata": {
    "openalex_id": "S...",
    "display_name": "Journal name",
    "issn_l": "1234-5678",
    "issn": ["1234-5678"],
    "type": "journal",
    "is_oa": true,
    "is_in_doaj": true
  },
  "abstract": {
    "status": "available",
    "text": "Reconstructed abstract text.",
    "provenance": "openalex.abstract_inverted_index"
  },
  "open_access": {
    "is_oa": true,
    "oa_status": "gold",
    "oa_url": "https://example.org/fulltext",
    "any_repository_has_fulltext": false
  },
  "oa_locations": [],
  "referenced_works": ["W..."],
  "referenced_works_count": 42,
  "cited_by_count": 100,
  "related_works": ["W..."],
  "topics": [],
  "flags": {"is_retracted": false, "is_paratext": false},
  "provenance": {
    "api": "openalex",
    "endpoint": "/works/{id}",
    "fetched_at": "2026-05-21T00:00:00Z"
  }
}
```

Normalize IDs:

- `openalex_id`: short ID without URL, e.g. `W2741809807`.
- `openalex_url`: full `https://openalex.org/W2741809807`.
- `doi`: DOI string without `https://doi.org/`, lowercased.
- `doi_url`: full DOI URL when DOI exists.
- `pmid`: numeric string without `PMID:`.
- `pmcid`: uppercase `PMC...`.

Unavailable reason codes:

| Reason | Meaning |
| --- | --- |
| `malformed-id` | User ID cannot be normalized |
| `unsupported-id` | ID type not supported by OpenAlex work lookup |
| `not-found` | OpenAlex returned 404 or empty search result |
| `no-abstract` | `abstract_inverted_index` missing/null |
| `partial-abstract` | Reconstruction had gaps or inconsistent positions |
| `no-oa` | No OA URL/location found |
| `closed-access` | `open_access.is_oa=false` |
| `no-pdf-url` | OA location exists but direct PDF URL absent |
| `fulltext-not-in-openalex` | OpenAlex has metadata only; use other full-text source |
| `rate-limited` | `429` after retries |
| `timeout` | Request timeout after retries |
| `upstream-error` | 5xx or invalid upstream response after retries |
| `partial-metadata` | Required fields missing from otherwise valid work |

## Source docs

- OpenAlex API docs: `https://docs.openalex.org/`
- OpenAlex OpenAPI JSON: `https://docs.openalex.org/api-reference/openapi.json`
- Works API reference: `https://docs.openalex.org/api-reference/works`
- Rate limits and authentication: `https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication`
- Search entities: `https://docs.openalex.org/how-to-use-the-api/get-lists-of-entities/search-entities`
- Filter entity lists: `https://docs.openalex.org/how-to-use-the-api/get-lists-of-entities/filter-entity-lists`
- Select fields: `https://docs.openalex.org/how-to-use-the-api/get-lists-of-entities/select-fields`
- Page and sort lists: `https://docs.openalex.org/how-to-use-the-api/get-lists-of-entities/page-and-sort-entity-lists`
- Group lists: `https://docs.openalex.org/how-to-use-the-api/get-lists-of-entities/group-entity-lists`
- Local fetched spec: `../../references/api-specs/raw/openalex-openapi.json`
