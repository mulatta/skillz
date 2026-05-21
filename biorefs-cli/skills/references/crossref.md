# Crossref reference export notes

Use these notes when `biorefs-cli` needs DOI metadata, citation export, or reference extraction. Do not invent citation fields. Report missing metadata explicitly.

## Source role and priority

Citation source priority:

1. PubMed metadata when PMID exists.
1. Crossref for DOI metadata and DOI content negotiation.
1. OpenAlex as enrichment or fallback.

Crossref is strongest for DOI registration metadata. It may be publisher-centric, non-biomedical, or less detailed than PubMed for biomedical articles. Prefer PubMed journal/article metadata for PMID-backed biomedical records, then use Crossref to fill DOI-level fields, publisher data, licenses, links, and deposited references.

## REST API basics

Base URL:

```text
https://api.crossref.org
```

Important endpoints:

```text
GET /works/{doi}
GET /works?query.bibliographic={text}&rows=5
GET /works?query.title={title}&rows=5
GET /works?query.author={author}&rows=5
GET /works?filter=doi:{doi}
GET /works?filter=from-pub-date:YYYY-MM-DD,until-pub-date:YYYY-MM-DD
GET /works?filter=type:journal-article,from-pub-date:YYYY-01-01
```

Polite client requirements:

- Send descriptive `User-Agent`, including package/version and contact email.
- Include `mailto=<email>` query parameter when available, or email in User-Agent.
- Reuse configured email such as `OPENALEX_EMAIL` only if user intends it as public API contact; otherwise add future `CROSSREF_EMAIL` config.
- Bound concurrency and retry with backoff. Respect `429`, `403`, and `5xx` responses.
- Use timeouts and XDG cache. CLI command remains synchronous.

Example User-Agent:

```text
biorefs-cli/0.1 (mailto:<configured-email>)
```

## DOI normalization

Normalize DOI before lookup:

- Strip URL/resolver prefixes: `https://doi.org/`, `http://dx.doi.org/`, `doi:`.
- Trim whitespace and trailing punctuation copied from prose.
- Preserve DOI suffix case for display if present, but compare case-insensitively.
- URL-encode DOI path segment for `/works/{doi}` because DOI contains `/`.

Example:

```text
10.1158/2159-8290.CD-12-0049
GET https://api.crossref.org/works/10.1158%2F2159-8290.CD-12-0049
```

If `/works/{doi}` returns `404`, report `doi-not-found` and do not create a synthetic citation from partial user input.

## Lookup strategy

### DOI lookup

Use exact DOI lookup first when DOI is known:

```text
GET /works/{doi}
```

Use `HEAD /works/{doi}` only for quick existence checks. Fetch JSON for citation export.

### Bibliographic lookup

When no DOI exists, search with the best available citation string:

```text
GET /works?query.bibliographic={title journal author year}&rows=5
```

For tighter matching, combine fields:

```text
GET /works?query.title={title}&query.author={author}&filter=from-pub-date:YYYY-01-01,until-pub-date:YYYY-12-31&rows=5
```

Use filters only when they reduce ambiguity:

- `type:journal-article` for journal article export.
- `from-pub-date` / `until-pub-date` for known publication year/date.
- `from-created-date` / `until-created-date` for Crossref deposit windows, not publication date.
- `has-reference:true` when collecting deposited reference lists.
- `has-license:true` when license metadata is needed.
- `issn:{issn}` when journal identity is known.

Ambiguous title matches must return candidate records with scores and identifiers, not a guessed citation. Prefer exact DOI, exact PMID-derived DOI, normalized title match, journal/container match, author/year match, then page/volume/issue match.

## Content negotiation for BibTeX and RIS

Prefer PubMed-derived citation export when PMID exists. Use Crossref content negotiation when DOI exists and BibTeX/RIS source text is requested.

DOI resolver pattern:

```text
GET https://doi.org/{doi}
Accept: application/x-bibtex

GET https://doi.org/{doi}
Accept: application/x-research-info-systems
```

Crossref transform pattern when supported by Crossref for the requested media type:

```text
GET https://api.crossref.org/works/{urlencoded-doi}/transform/application/x-bibtex
GET https://api.crossref.org/works/{urlencoded-doi}/transform/application/x-research-info-systems
```

Implementation implications:

- `paper cite --doi DOI --format bibtex` may fetch BibTeX through DOI content negotiation.
- `paper cite --pmid PMID --format bibtex` should prefer PubMed metadata, then Crossref by DOI if PubMed lacks needed export fields.
- `paper convert --doi DOI` should return normalized JSON with source provenance and optionally raw citation exports.
- `export --format bibtex|ris` should emit one entry per deduplicated work and include missing-field warnings separately.
- If RIS content negotiation is unsupported or fails, generate RIS locally from normalized metadata and record `generated_from=crossref-json`.
- If BibTeX content negotiation fails, generate BibTeX locally only from known fields and mark missing fields.

## Key Crossref work fields

Map Crossref `message` fields into normalized reference records:

| Crossref field | Normalized use |
| --- | --- |
| `DOI` | canonical DOI |
| `title[]` | title; first title preferred, keep alternatives if needed |
| `subtitle[]` | subtitle when present |
| `container-title[]` | journal/book/proceedings title |
| `short-container-title[]` | journal abbreviation candidate |
| `issued`, `published-print`, `published-online` | publication date candidates |
| `author[]` | authors; preserve order, given/family/ORCID/affiliation |
| `editor[]` | editors for books/proceedings |
| `volume`, `issue`, `page`, `article-number` | location fields |
| `publisher` | publisher name |
| `type` | work type, e.g. `journal-article`, `book-chapter` |
| `ISSN`, `ISBN` | serial/book identifiers |
| `license[]` | license URLs, start dates, delay metadata |
| `link[]` | full-text or resource links; verify access separately |
| `reference[]` | deposited reference list for extraction |
| `reference-count`, `is-referenced-by-count` | counts, not complete citation graph |
| `URL` | Crossref landing URL |
| `subject[]` | publisher/Crossref subject labels |
| `member`, `prefix`, `deposited`, `indexed` | provenance/debug fields |

Date handling:

- Crossref dates use `date-parts` arrays with variable precision.
- Preserve precision: year-only is not full date.
- Prefer PubMed electronic/print publication dates for PMID records unless Crossref has more complete DOI-specific date and no conflict.
- Report missing month/day rather than inventing `01-01`.

Name handling:

- Preserve author order exactly.
- Use `family`/`given` when present.
- Report missing author list as `missing: author`; do not use publisher or title words as author substitutes.

## Reference extraction

For DOI/BibTeX/RIS source extraction:

- Use Crossref `reference[]` when DOI metadata includes deposited references.
- Preserve raw unstructured reference text from fields such as `unstructured`.
- Extract child identifiers (`DOI`, `article-title`, `journal-title`, `volume`, `year`, `first-page`, etc.) only when present.
- Resolve reference DOIs separately with bounded concurrency and cache.
- If a reference lacks DOI/PMID and title match is ambiguous, keep it as unresolved with missing fields.

## Deduplication and conflicts

Deduplicate across PubMed, Crossref, and OpenAlex using identifier priority:

1. PMID exact match.
1. DOI exact normalized match.
1. PMCID exact match.
1. OpenAlex work ID exact match.
1. High-confidence bibliographic match: normalized title + first author + year + container.

Conflict resolution:

- Keep all source provenance in JSON.
- Prefer PubMed for PMID, biomedical title, abstract-related metadata, MeSH, journal details, and author lists.
- Prefer Crossref for DOI registration, publisher, license/link, and deposited references.
- Prefer OpenAlex for OA locations, citation graph, concepts, and enrichment.
- If fields conflict materially, choose priority source and record conflict in `warnings` or `sources[].conflicts`.
- Never merge two records on title alone.

## Error handling

Return structured errors/warnings:

- `doi-not-found`: `/works/{doi}` returned `404`.
- `rate-limited`: `429`; retry after backoff, then report if exhausted.
- `blocked`: `403`; stop aggressive retries and mention contact/User-Agent configuration.
- `server-error`: `5xx`; retry with backoff.
- `ambiguous-match`: multiple plausible `/works` matches; return candidates.
- `incomplete-date`: date has only year or year/month.
- `missing-author`: no usable author/editor list.
- `missing-title`: no title in chosen source.
- `content-negotiation-failed`: BibTeX/RIS negotiation failed; generated local export if possible.

No invented citations: if required fields are absent, emit export with available fields and separate missing-field report, or fail when caller requested strict mode.

## CLI implications

`paper cite`:

- Accept PMID, DOI, PMCID, or title query.
- Resolve PMID through PubMed first.
- Resolve DOI through Crossref when PubMed not available or when DOI citation export is requested.
- Output Markdown by default; JSON/BibTeX/RIS when requested.

`paper convert`:

- Normalize identifiers and return one structured record.
- Include `sources` array showing PubMed/Crossref/OpenAlex fields used.
- Include `missing` and `warnings` arrays.

`export --format bibtex|ris`:

- Export deduplicated records only.
- Keep stable citation keys; avoid changing keys when enrichment adds fields.
- Use DOI content negotiation output when available, otherwise local formatter from normalized metadata.
- Emit warnings out-of-band from BibTeX/RIS text when possible, because citation formats cannot preserve all provenance.

## Source docs

- Crossref REST API documentation: `https://www.crossref.org/documentation/retrieve-metadata/rest-api/`
- Crossref REST API Swagger source: `https://api.crossref.org/swagger-docs`
- Crossref REST API base: `https://api.crossref.org`
- Crossref content negotiation docs: `https://www.crossref.org/documentation/retrieve-metadata/content-negotiation/`
- Crossref REST filters: `https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/`
- Crossref etiquette / tips: `https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/`
- DOI resolver: `https://doi.org/`
