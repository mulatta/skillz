# PubMed / PMC reference

Operational notes for `biorefs-cli paper` commands. Use direct HTTP APIs, legal open-access sources, and stable agent-oriented output.

## API roles

| API | Role |
| --- | --- |
| PubMed ESearch | Search article metadata and return PMIDs. |
| PubMed EFetch | Fetch PubMed XML metadata and abstracts. |
| ELink PubMed | Related papers, references, cited-by links when available. |
| PMC ID Converter | Convert PMID, PMCID, DOI, and manuscript IDs. |
| PMC EFetch | Fetch PMC article XML/JATS full text when available. |

Do not use Sci-Hub, paywalled scraping, or browser automation against publisher paywalls. Full text means legal OA/API-provided full text. Otherwise return abstract-only metadata plus structured unavailable reasons.

## Contents

- [API roles](#api-roles)
- [PubMed search](#pubmed-search)
- [PubMed fetch metadata](#pubmed-fetch-metadata)
- [PMC ID Converter](#pmc-id-converter)
- [PMC EFetch full text](#pmc-efetch-full-text)
- [Abstract-only vs full-text evidence](#abstract-only-vs-full-text-evidence)
- [Paper command implications](#paper-command-implications)
- [Common unavailable/failure reasons](#common-unavailablefailure-reasons)
- [Parsing gotchas](#parsing-gotchas)

## PubMed search

Use Entrez ESearch:

```text
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi
  ?db=pubmed
  &term=<query>
  &retmode=json
  &retstart=0
  &retmax=<limit>
  &tool=biorefs-cli
  &email=<configured email>
```

Common parameters:

- `term`: PubMed query with field tags when needed, such as `BRCA1[Title/Abstract]`.
- `sort`: e.g. relevance/date variants supported by PubMed.
- `datetype`, `mindate`, `maxdate`, `reldate`: date filters.
- `usehistory=y`: needed for large result sets, paging, and later fetch/link operations.
- `retstart`, `retmax`: page through results.

`paper search` implications:

- Return PMID list, count, query translation, and optional compact summaries.
- Keep user query and PubMed query translation visible.
- Do not silently correct misspellings; use ESpell suggestions only as suggestions.
- For `--json`, include stable pagination fields: `count`, `limit`, `offset`, `ids`.

## PubMed fetch metadata

Use Entrez EFetch:

```text
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
  ?db=pubmed
  &id=<pmid[,pmid...]>
  &retmode=xml
  &tool=biorefs-cli
  &email=<configured email>
```

Parse these fields when present:

| Field | XML source notes |
| --- | --- |
| PMID | `MedlineCitation/PMID`; include version if present. |
| DOI | `PubmedData/ArticleIdList/ArticleId[@IdType="doi"]`; normalize lowercase where safe. |
| PMCID | `ArticleIdList/ArticleId[@IdType="pmc"]`; preserve `PMC` prefix. |
| Title | `Article/ArticleTitle`; flatten inline tags. |
| Abstract | `Article/Abstract/AbstractText`; preserve structured sections. |
| Authors | `AuthorList/Author`; support personal and collective authors. |
| Affiliations | `AffiliationInfo/Affiliation`; attach to author when possible. |
| Journal | `Journal/Title`, `ISOAbbreviation`, ISSN, volume, issue, pages. |
| Publication types | `PublicationTypeList`. |
| MeSH | `MeshHeadingList`; include descriptor, qualifiers, major-topic flags. |
| Grants | `GrantList`; include agency, country, grant ID, acronym. |
| Dates | publication date, electronic publication date, PubMed history dates, revised/completed dates. |
| Keywords | `KeywordList` when present. |
| Language | `Language`. |

Structured abstract handling:

- Each `AbstractText` becomes one section.
- Section title comes from `Label` first, then `NlmCategory`, then `null`.
- Preserve order.
- Provide joined plain-text abstract for simple display.

Recommended normalized shape:

```json
{
  "identifiers": {"pmid": "123", "pmcid": "PMC123", "doi": "10.x/y"},
  "title": "...",
  "abstract": {
    "text": "joined abstract text",
    "sections": [
      {"label": "BACKGROUND", "nlm_category": "BACKGROUND", "text": "..."}
    ]
  },
  "authors": [
    {"family": "...", "given": "...", "collective": null, "affiliations": ["..."]}
  ],
  "journal": {"title": "...", "iso_abbreviation": "...", "volume": "...", "issue": "...", "pages": "..."},
  "publication_types": [],
  "mesh": [],
  "grants": [],
  "dates": {},
  "evidence_level": "abstract-only"
}
```

## PMC ID Converter

Use the PMC ID Converter before full-text fetch and for `paper convert`.

Endpoint:

```text
GET https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/
  ?ids=<pmid-or-pmcid-or-doi[,more...]>
  &format=json
  &tool=biorefs-cli
  &email=<configured email>
```

Inputs:

- PMID, e.g. `23103855`
- PMCID, e.g. `PMC3531190`
- DOI, e.g. `10.1158/2159-8290.cd-12-0049`

Return fields may include:

- `pmid`
- `pmcid`
- `doi`
- `versions`
- `status`, warnings, or error messages

Rules:

- Batch IDs, but keep per-input result mapping.
- Preserve failed conversions as structured records.
- Treat missing PMCID as `no-pmcid`, not a network or parse failure.
- Use PubMed `ArticleIdList` as a fallback/check, not as the only converter.

`paper convert` implications:

- Accept any one of PMID, PMCID, DOI.
- Return all known IDs plus source provenance.
- Report ambiguous or missing IDs explicitly.

## PMC EFetch full text

Use Entrez EFetch for PMC records:

```text
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
  ?db=pmc
  &id=<pmcid-or-pmc-uid>
  &retmode=xml
  &tool=biorefs-cli
  &email=<configured email>
```

PMC XML is JATS/NLM article XML when full text is available. Parse separately from PubMed XML.

Extract:

| Data | JATS source notes |
| --- | --- |
| Article metadata | `front/article-meta`, title group, contributors, affiliations, journal metadata. |
| IDs | article IDs with `pub-id-type`: `pmid`, `pmcid`, `doi`, publisher IDs. |
| Abstract | `abstract`, including structured sections. |
| Body sections | `body/sec` recursively; preserve section path and order. |
| Paragraphs | `p`, list items, quoted text; flatten inline markup. |
| Tables | `table-wrap`, `caption`, `label`, table content summary or structured rows when feasible. |
| Figures | `fig`, `caption`, `label`, graphic href when present. |
| Supplementary material | `supplementary-material` metadata and links when present. |
| References | `back/ref-list/ref`; parse citation text and IDs. |
| Funding/license | `funding-group`, `permissions`, license URL/type. |

Section extraction rules:

- Preserve hierarchy: `Introduction > Methods > Sequencing`.
- Store normalized section type when obvious: `abstract`, `introduction`, `methods`, `results`, `discussion`, `conclusion`, `references`, `unknown`.
- Keep original section title.
- Preserve order index and source XPath-like path for traceability.
- `--sections methods,results` filters after parsing, not during HTTP fetch.
- Keep captions as evidence text with `evidence_kind=figure-caption` or `table-caption`.

Recommended full-text evidence shape:

```json
{
  "identifiers": {"pmid": "123", "pmcid": "PMC123", "doi": "10.x/y"},
  "fulltext": {
    "status": "available",
    "source": "pmc",
    "license": {"type": "...", "url": "..."},
    "sections": [
      {"path": ["Results"], "type": "results", "title": "Results", "text": "...", "order": 4}
    ],
    "figures": [
      {"label": "Figure 1", "caption": "..."}
    ],
    "tables": [
      {"label": "Table 1", "caption": "..."}
    ],
    "references": []
  },
  "evidence_level": "full-text"
}
```

## Abstract-only vs full-text evidence

Agents must know evidence scope.

Use `evidence_level`:

- `metadata-only`: title/authors/journal only; no abstract.
- `abstract-only`: PubMed abstract available; no full text parsed.
- `full-text`: PMC or other legal OA full text parsed.

For claims, include `evidence_source`:

```json
{
  "claim": "...",
  "evidence_level": "abstract-only",
  "evidence_source": {
    "kind": "abstract-section",
    "section": "RESULTS",
    "pmid": "123"
  }
}
```

Never present abstract-only evidence as if methods/results full text was inspected.

## Paper command implications

### `paper search`

- Use PubMed ESearch by default.
- Optionally hydrate top results with ESummary or PubMed EFetch metadata.
- Return concise Markdown for humans and stable JSON for agents.

### `paper fetch`

- Accept PMID, PMCID, DOI.
- Normalize IDs with PMC ID Converter and PubMed XML.
- Return PubMed metadata and abstract.
- Do not fetch full text unless requested or an explicit option asks for it.

### `paper fulltext`

Resolution order:

1. Use provided PMCID directly.
1. Convert PMID/DOI to PMCID with PMC ID Converter.
1. Fetch PMC XML through EFetch.
1. If unavailable, return structured failure for later fallback APIs.

Return full text only when legally available through supported sources. Include license metadata if present.

### `paper related`

Use ELink from PubMed to PubMed:

- Similar/neighbor papers: standard PubMed related links.
- References and cited-by: use returned link sets when available.

Return mode, source PMID, target PMIDs, link name, score if returned, and provenance. Empty related lists are valid successful results.

### `paper convert`

Use PMC ID Converter first, then PubMed XML `ArticleIdList` as fallback/check. Return per-input records with `pmid`, `pmcid`, `doi`, status, and provenance.

### `paper cite`

Use PubMed XML metadata to build citations:

- Required: title, authors or collective author, journal/book source, year.
- Include DOI/PMID/PMCID when present.
- If fields are missing, emit citation with missing-field warnings; do not invent data.
- BibTeX keys should be deterministic from first author/year/title or PMID fallback.

## Common unavailable/failure reasons

Return failures as data:

```json
{
  "status": "unavailable",
  "reason": "no-pmcid",
  "input": {"pmid": "123"},
  "tried": [
    {"source": "pmc-id-converter", "status": "miss"},
    {"source": "pubmed-article-id-list", "status": "miss"}
  ],
  "retryable": false
}
```

Reason codes:

| Reason | Meaning | Retryable |
| --- | --- | --- |
| `not-found` | No PubMed/PMC record for ID/query. | false |
| `invalid-id` | ID format cannot be routed. | false |
| `no-pmcid` | PMID/DOI has no PMCID mapping. | false |
| `pmc-not-available` | PMCID exists but PMC XML/full text was not returned. | false |
| `abstract-missing` | PubMed record has no abstract. | false |
| `fulltext-unavailable` | No legal full-text source found in configured workflow. | false |
| `license-restricted` | Full text exists but reuse/access mode is not allowed by current policy. | false |
| `rate-limited` | API returned throttling response. | true |
| `timeout` | Request timed out. | true |
| `upstream-error` | HTTP 5xx or malformed upstream response. | true |
| `parse-error` | Response received but parser failed. | maybe |

Include:

- `input` identifiers
- `normalized_identifiers` when known
- `tried` source list
- `http_status` when relevant
- `retry_after` when relevant
- `raw_saved` only if raw payload is cached and safe to reference

## Parsing gotchas

- PubMed and PMC XML are different formats; do not use one parser for both.
- Inline tags appear inside titles, abstracts, paragraphs, and references.
- Math, superscripts, subscripts, italics, and external links should be flattened without losing readable text.
- Author affiliations may be global in PMC and per-author in PubMed.
- Dates can be partial or textual; keep raw date parts and normalized date when possible.
- References may lack DOI/PMID; keep raw citation text.
- PMCID formats include `PMC` prefix; Entrez PMC UID may be numeric. Preserve display PMCID in output.
- DOI matching should be case-insensitive for lookup but preserve original when displaying if needed.

## Source docs

- PubMed E-utilities and PubMed XML: `https://www.ncbi.nlm.nih.gov/books/NBK25501/`
- PubMed XML element descriptions: `https://www.ncbi.nlm.nih.gov/books/NBK3828/`
- PMC ID Converter API: `https://www.ncbi.nlm.nih.gov/pmc/tools/id-converter-api/`
- PMC article XML / JATS guidance: `https://www.ncbi.nlm.nih.gov/pmc/tools/`
