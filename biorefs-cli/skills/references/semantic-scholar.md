# Semantic Scholar reference

Semantic Scholar support is optional/deferred for `biorefs-cli`. Use OpenAlex first for DOI/PMID/PMCID mapping, open-access location discovery, and citation graph basics. Add Semantic Scholar later when agent needs influential citations, TLDR summaries, fields of study, recommendations, citation contexts/intents, or `openAccessPdf` fallback.

## Base URLs and authentication

- Graph API base URL: `https://api.semanticscholar.org/graph/v1`
- Recommendations API base URL: `https://api.semanticscholar.org/recommendations/v1`
- API key is optional. Do not require it for MVP.
- If configured, send key as case-sensitive header:

```http
x-api-key: ${SEMANTIC_SCHOLAR_API_KEY}
```

Do not put API key in query parameters. Do not print key in logs, cache keys, errors, or debug output.

## Paper ID formats

Graph paper endpoints accept `paper_id` path values in these forms:

| Input | Semantic Scholar path value |
| --- | --- |
| Semantic Scholar paper ID | `649def34f8be52c8b66281af98ae884c09aef38b` |
| CorpusID | `CorpusId:215416146` |
| DOI | `DOI:10.18653/v1/N18-3011` |
| PMID | `PMID:19872477` |
| PMCID | `PMCID:2323736` or normalized PMCID value accepted by API |
| arXiv | `ARXIV:2106.15928` |
| ACL | `ACL:W12-3903` |
| MAG | `MAG:112218234` |
| URL | `URL:https://arxiv.org/abs/2106.15928v1` |

Normalize user-facing aliases internally, but preserve original input under provenance. Prefer exact identifiers over title search.

## Fields parameter

Most Graph and Recommendations endpoints accept `fields` as comma-separated field names. If omitted, responses are minimal, commonly `paperId` plus `title`.

Recommended paper fields for enrichment:

```text
paperId,corpusId,externalIds,url,title,abstract,venue,year,authors,citationCount,referenceCount,influentialCitationCount,tldr,openAccessPdf,fieldsOfStudy,s2FieldsOfStudy,publicationTypes,publicationDate,journal
```

Use smaller field sets for graph pagination. Add `citations` or `references` only on single-paper detail calls when explicitly needed because nested graph payloads can become large.

## Paper lookup

### Single paper

```http
GET /paper/{paper_id}?fields=paperId,corpusId,externalIds,title,abstract,venue,year,authors,citationCount,referenceCount,influentialCitationCount,tldr,openAccessPdf,fieldsOfStudy,publicationTypes
```

Use for DOI/PMID/PMCID/arXiv/CorpusID/Semantic Scholar ID lookup. Handle:

- `200`: return normalized paper record.
- `404`: return structured miss, not exception-only failure.
- `400`: report unsupported identifier or unsupported fields.

### Batch paper lookup

```http
POST /paper/batch?fields=paperId,corpusId,externalIds,title,year,authors,citationCount,influentialCitationCount,tldr,openAccessPdf,fieldsOfStudy,publicationTypes
Content-Type: application/json

{"ids":["DOI:10.18653/v1/N18-3011","PMID:19872477","CorpusId:215416146"]}
```

Use batch lookup for enrichment of known IDs. Split large input into bounded batches. Preserve input order in CLI output where possible. Treat null/missing batch entries as per-item misses and continue returning successful records.

## Search endpoints

### Relevance search

```http
GET /paper/search?query=BRCA1%20PARP%20inhibitor&limit=20&fields=paperId,externalIds,title,year,authors,citationCount,influentialCitationCount,tldr
```

Use for small interactive searches. Parameters include `query`, `offset`, `limit` (up to 100), `fields`, `year`, `publicationDateOrYear`, `publicationTypes`, `fieldsOfStudy`, `venue`, `minCitationCount`, and `openAccessPdf` filter.

### Bulk search

```http
GET /paper/search/bulk?query=BRCA1%20PARP%20inhibitor&fields=paperId,externalIds,title,year,authors&token=...
```

Use only for large discovery jobs. It uses `token` pagination rather than offset pagination. Keep CLI defaults small; do not make bulk search default agent behavior.

### Title match

```http
GET /paper/search/match?query=Construction%20of%20the%20Literature%20Graph%20in%20Semantic%20Scholar&fields=paperId,externalIds,title,year,authors
```

Use as fallback when no DOI/PMID/PMCID/arXiv exists and title is known. Treat title matches as lower confidence than identifier lookup. Include match score in provenance if returned.

## Citations and references

### Citing papers

```http
GET /paper/{paper_id}/citations?limit=100&offset=0&fields=paperId,externalIds,title,year,authors,citationCount,influentialCitationCount,fieldsOfStudy
```

Response items contain citation metadata plus `citingPaper`. Useful fields on citation edge:

- `contexts`: text snippets where citation appears.
- `intents`: citation intent labels.
- `contextsWithIntent`: snippets paired with intents.
- `isInfluential`: Semantic Scholar influential citation flag.

### Referenced papers

```http
GET /paper/{paper_id}/references?limit=100&offset=0&fields=paperId,externalIds,title,year,authors,citationCount,influentialCitationCount,fieldsOfStudy
```

Response items contain reference metadata plus `citedPaper`. Use for backward citation graph enrichment or bibliography inspection.

Both endpoints support `offset`, `limit` (up to 1000), and `fields`. Paginate until `next` is absent or requested CLI limit is reached.

## Key paper fields

| Field | Meaning | Notes |
| --- | --- | --- |
| `paperId` | Primary Semantic Scholar paper ID | Stable Graph API identifier. |
| `corpusId` | Secondary numeric Semantic Scholar ID | Common in S2 datasets. |
| `externalIds` | DOI, PubMed, PubMedCentral, ArXiv, ACL, DBLP, MAG, CorpusId | Use for cross-source normalization. |
| `title` | Paper title | May differ from PubMed/OpenAlex punctuation. |
| `abstract` | Abstract text | May be absent for legal reasons. |
| `venue` | Journal/conference display name | Prefer PubMed journal metadata for biomedical citation export. |
| `year` | Publication year | Use `publicationDate` when date precision matters. |
| `authors` | Author IDs and names by default | Request nested author fields only when needed. |
| `citationCount` | Total citing paper count | Source-specific count; do not merge blindly with OpenAlex. |
| `referenceCount` | Total referenced paper count | Source-specific count. |
| `influentialCitationCount` | Count of citations flagged influential | Main Semantic Scholar value-add. |
| `tldr` | Model and short summary text | Optional value-add; may be missing. |
| `openAccessPdf` | PDF URL, OA status, license, disclaimer | Use as fallback after PMC/Europe PMC/OpenAlex. Verify license/disclaimer. |
| `fieldsOfStudy` | High-level fields from external sources | Optional classification. |
| `s2FieldsOfStudy` | Field classifications with source | Useful for Semantic Scholar model provenance. |
| `publicationTypes` | Article type labels | Useful filters, not PubMed publication type replacement. |

## OpenAlex vs Semantic Scholar

Prefer OpenAlex for MVP when task needs:

- DOI/PMID/PMCID/OpenAlex ID mapping.
- `best_oa_location` and `locations` for open-access full text.
- Basic citation/cited-by graph with broad coverage.
- Works metadata that aligns with OpenAlex concepts/sources.

Use Semantic Scholar as optional enrichment when task needs:

- Influential citation counts or per-edge `isInfluential`.
- Citation contexts and intents.
- TLDR summaries.
- `fieldsOfStudy` or `s2FieldsOfStudy` classifications.
- Recommendations from seed papers.
- `openAccessPdf` fallback when primary OA sources fail.
- Semantic Scholar paper URL or CorpusID interoperability.

Never let Semantic Scholar replace PubMed/PMC as biomedical source of record. For citation export and biomedical metadata, prefer PubMed/Crossref/OpenAlex depending on available identifier and command purpose.

## Recommendations API

Recommendations are optional discovery helpers, not evidence sources. Use after user asks for related papers or exploration beyond known citation graph.

### Single seed paper

```http
GET /papers/forpaper/{paper_id}?from=recent&limit=20&fields=paperId,externalIds,title,year,authors,citationCount,influentialCitationCount,tldr,fieldsOfStudy
```

- `from=recent`: default pool.
- `from=all-cs`: broader computer-science-oriented pool; avoid for biomedical default unless user asks.
- `limit` maximum is 500.

### Positive/negative seed lists

```http
POST /papers/?limit=20&fields=paperId,externalIds,title,year,authors,citationCount,influentialCitationCount,tldr,fieldsOfStudy
Content-Type: application/json

{
  "positivePaperIds": ["649def34f8be52c8b66281af98ae884c09aef38b", "ARXIV:1805.02262"],
  "negativePaperIds": []
}
```

Return recommendations separately from citations/references. Label result provenance as `semantic_scholar_recommendations`, not as direct citation evidence.

## Rate limits, retries, timeouts, cache

- API key raises rate limits but is optional. Without key, keep concurrency and request rate conservative.
- Internals should use async HTTP with bounded concurrency; CLI remains synchronous.
- Use per-host rate limiter shared by Graph and Recommendations calls.
- Retry only transient failures: `429`, `500`, `502`, `503`, `504`, connection reset, and timeout.
- Honor `Retry-After` when present. Otherwise use exponential backoff with jitter.
- Do not retry `400` field/query errors or `404` misses.
- Set connect and total request timeouts; return structured unavailable/error records when exhausted.
- Cache GET responses and successful batch item results in XDG cache. Include endpoint, normalized ID/query, fields, pagination params, and API version in cache key. Do not include API key.
- Use stale cache only when clearly marked in provenance.

## Batching and partial results

- Prefer `/paper/batch` over many `/paper/{paper_id}` calls for known IDs.
- Split large batches before API rejects oversized payloads; shrink and retry once on payload-size `400` if response says response would exceed maximum size.
- Continue on per-item misses. Output should include successes plus `missing` entries containing input identifier and source.
- For citation/reference pagination, stop at user-requested limit even if more pages exist.
- If page fails after retries, return partial records with `partial=true`, `next_offset` or `next_token` when available, and error provenance.

## Normalized output and provenance

Suggested normalized paper shape:

```json
{
  "ids": {
    "semantic_scholar_paper_id": "5c5751d45e298cea054f32b392c12c61027d2fe7",
    "semantic_scholar_corpus_id": 215416146,
    "doi": "10.18653/V1/2020.ACL-MAIN.447",
    "pmid": null,
    "pmcid": null,
    "arxiv": null
  },
  "title": "Construction of the Literature Graph in Semantic Scholar",
  "abstract": null,
  "venue": "Annual Meeting of the Association for Computational Linguistics",
  "year": 2018,
  "authors": [{"name": "Waleed Ammar", "semantic_scholar_author_id": null}],
  "counts": {
    "citations": 453,
    "references": 59,
    "influential_citations": 90
  },
  "semantic_scholar": {
    "tldr": {"model": "tldr@v2.0.0", "text": "..."},
    "fields_of_study": ["Computer Science"],
    "s2_fields_of_study": [],
    "publication_types": ["Journal Article"],
    "open_access_pdf": {
      "url": "https://example.org/paper.pdf",
      "status": "HYBRID",
      "license": "CCBY",
      "disclaimer": "..."
    },
    "url": "https://www.semanticscholar.org/paper/..."
  },
  "provenance": [
    {
      "source": "semantic_scholar_graph",
      "endpoint": "/paper/{paper_id}",
      "input": "DOI:10.18653/v1/N18-3011",
      "fields": ["paperId", "externalIds", "title"],
      "retrieved_at": "2026-05-21T00:00:00Z",
      "partial": false
    }
  ]
}
```

Identifier normalization:

- `externalIds.DOI` -> `ids.doi`
- `externalIds.PubMed` or `externalIds.Medline` -> `ids.pmid` only when value is PMID-compatible
- `externalIds.PubMedCentral` -> `ids.pmcid`
- `externalIds.ArXiv` -> `ids.arxiv`
- `paperId` -> `ids.semantic_scholar_paper_id`
- `corpusId` or `externalIds.CorpusId` -> `ids.semantic_scholar_corpus_id`

Counts from different sources are not interchangeable. Keep Semantic Scholar counts under Semantic Scholar provenance or source-qualified fields.

## Source docs

- Graph API Swagger: `https://api.semanticscholar.org/graph/v1/swagger.json`
- Recommendations API Swagger: `https://api.semanticscholar.org/recommendations/v1/swagger.json`
- Semantic Scholar API overview: `https://www.semanticscholar.org/product/api`
- Semantic Scholar API FAQ/community notes: `https://github.com/allenai/s2-folks/blob/main/FAQ.md`
- Influential citations FAQ: `https://www.semanticscholar.org/faq#influential-citations`
- Citation intent FAQ: `https://www.semanticscholar.org/faq#citation-intent`
