# NCBI Entrez / E-utilities reference

Operational notes for `biorefs-cli` direct HTTP clients. Use E-utilities as a small generic escape hatch, not as an EDirect pipeline clone.

## Base URL and endpoints

Base URL:

```text
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
```

Endpoints:

| Endpoint | Path | Main use |
| --- | --- | --- |
| ESearch | `esearch.fcgi` | Search an Entrez database; return UIDs or history token. |
| ESummary | `esummary.fcgi` | Fetch compact document summaries for UIDs/history. |
| EFetch | `efetch.fcgi` | Fetch full records in database-specific formats. |
| ELink | `elink.fcgi` | Link records across databases or find related records. |
| EPost | `epost.fcgi` | Upload large UID sets to history server. |
| ESpell | `espell.fcgi` | Spell-check search terms. |
| ECitMatch | `ecitmatch.cgi` | Match raw citation strings to PMIDs. |

Always include:

- `tool=biorefs-cli`
- `email=<configured email>` from `NCBI_EMAIL` or config
- `api_key=<configured key>` only when present

Prefer `retmode=json` for ESearch, ESummary, ELink, ESpell, and other endpoints that support JSON. EFetch remains database/format-specific; PubMed metadata is XML, sequences are FASTA/GenBank/XML, and PMC full text is XML/JATS.

## Rate limits and request shaping

NCBI service limits:

- No API key: about 3 requests/second.
- API key: about 10 requests/second.

Client behavior:

- Enforce one shared token bucket per NCBI host.
- Use bounded concurrency; do not fan out one task per UID.
- Batch IDs for ESummary/EFetch/ELink. Use conservative batches such as 100-500 UIDs, smaller when records are large.
- Use retries with exponential backoff for HTTP 429, 5xx, connect resets, and transient timeouts.
- Honor `Retry-After` if present.
- Use explicit connect/read timeouts.
- Cache stable metadata under XDG cache paths.

## History server, batching, and pagination

Use `usehistory=y` on ESearch when result sets may be paged, linked, summarized, or fetched later.

ESearch flow:

```text
GET esearch.fcgi?db=pubmed&term=BRCA1&usehistory=y&retmode=json&retmax=0
```

Persist from response:

- `WebEnv`
- `QueryKey`
- `Count`

Page with:

- `retstart=<zero-based offset>`
- `retmax=<page size>`

Use history directly with ESummary/EFetch/ELink:

```text
GET esummary.fcgi?db=pubmed&query_key=1&WebEnv=...&retstart=0&retmax=200&retmode=json
GET efetch.fcgi?db=pubmed&query_key=1&WebEnv=...&retstart=0&retmax=200&retmode=xml
```

Use EPost for large UID sets or when URLs would be long:

```text
POST epost.fcgi
Content-Type: application/x-www-form-urlencoded

db=pubmed&id=123,456,789&tool=biorefs-cli&email=...
```

Then use returned `WebEnv` and `query_key`. Prefer POST for large ID sets even if GET works.

## Generic `ncbi` command mapping

Keep commands small and predictable:

| CLI command | E-utility | Required inputs | Output |
| --- | --- | --- | --- |
| `ncbi search` | ESearch | `--db`, `--query` | UIDs, count, query translation, optional history token. |
| `ncbi summary` | ESummary | `--db`, `--id` or history | Normalized summary records plus raw source option. |
| `ncbi fetch` | EFetch | `--db`, `--id` or history, `--format` | Database-specific records; parsed where supported. |
| `ncbi link` | ELink | `--dbfrom`, `--db`, `--id` | Linked UIDs grouped by source UID and link name. |

Examples:

```bash
biorefs-cli ncbi search --db pubmed --query 'BRCA1[Title/Abstract]' --limit 20 --json
biorefs-cli ncbi summary --db gene --id 672 --json
biorefs-cli ncbi fetch --db protein --id NP_009225 --format fasta
biorefs-cli ncbi link --dbfrom gene --db pubmed --id 672 --json
```

Do not expose an `xtract` clone. Return normalized JSON and optional raw XML/JSON for debugging.

## Relevant Entrez databases

First-class design targets:

| DB | Role |
| --- | --- |
| `pubmed` | Article metadata, abstracts, citation links. |
| `pmc` | PMC records and full-text XML when available. |
| `gene` | NCBI Gene records and literature/entity links. |
| `protein` | Protein/RefSeq protein records and FASTA. |
| `nuccore` | Nucleotide/RefSeq RNA/DNA records and FASTA. |
| `taxonomy` | Organism/taxon lookup and normalization. |

Other Entrez databases remain available through `ncbi search/fetch/summary/link`. Add first-class commands only when output can be normalized and tested.

NCBI Datasets API is separate. It may help with genome/gene package workflows, but it does not replace Entrez for PubMed/PMC and link traversal.

## ELink workflows

General request shape:

```text
GET elink.fcgi?dbfrom=gene&db=pubmed&id=672&retmode=json
```

Normalize every result as:

```json
{
  "source_db": "gene",
  "source_id": "672",
  "target_db": "pubmed",
  "target_id": "...",
  "link_name": "gene_pubmed",
  "score": null,
  "provider": "ncbi-elink"
}
```

Important workflows:

- Gene -> PubMed: literature for a gene (`dbfrom=gene&db=pubmed`).
- PubMed -> Gene: genes mentioned/indexed for a paper (`dbfrom=pubmed&db=gene`).
- Gene -> Protein/Nucleotide: RefSeq and related sequence records (`dbfrom=gene&db=protein` or `db=nuccore`).
- Protein/Nucleotide -> Gene: map accessions back to gene where links exist.
- PubMed -> PubMed related: similar/neighbor articles (`dbfrom=pubmed&db=pubmed`).
- PubMed references/cited-by: use returned PubMed link sets when available. Do not assume every PMID has references or cited-by links.

Implementation rules:

- Preserve returned `LinkName`; link names vary by DB pair and record type.
- Group links by input UID; agents need to know which source produced each target.
- Support `cmd=neighbor`, `cmd=neighbor_score`, and history-based workflows when useful.
- Report empty link sets as successful empty results, not errors.

## Endpoint-specific notes

### ESearch

Common parameters:

- `db`
- `term`
- `retmode=json`
- `retstart`, `retmax`
- `sort` when supported by DB
- `field`, `datetype`, `mindate`, `maxdate`, `reldate` when useful
- `usehistory=y` for paging/link/fetch workflows

Return normalized:

- `db`
- `query`
- `count`
- `ids`
- `retstart`
- `retmax`
- `query_translation`
- `warnings`
- `history` when requested

### ESummary

Use for concise records and quick entity display. Schema differs by DB. Keep raw docsum available behind a debug/raw option.

Return stable core fields where present:

- `db`, `uid`, `title`, `name`, `description`
- `accession`, `version`
- `tax_id`, `organism`
- `pub_date`, `update_date`
- `extra` for DB-specific fields

### EFetch

Use when full record data is needed.

Common formats:

- PubMed: `db=pubmed&retmode=xml`
- PMC: `db=pmc&retmode=xml`
- Protein/Nucleotide FASTA: `rettype=fasta&retmode=text`
- Protein/Nucleotide GenBank: `rettype=gb&retmode=text` or XML when needed
- Gene: XML or docsum-style records depending on endpoint support

Normalize parsed output for first-class DBs. For generic DBs, return raw payload metadata plus content unless a parser exists.

### EPost

Use to turn large UID lists into history tokens. This avoids URL length failures and enables server-side paging.

### ESpell

Use as an optional helper for failed or low-result search. Never silently rewrite user queries; report suggestions.

### ECitMatch

Use to match raw citations to PMIDs. Input is pipe-delimited citation data. Treat matches as candidates unless enough fields agree.

## XML parsing gotchas

- PubMed XML mixes `MedlineCitation`, `PubmedData`, `Article`, `Journal`, and nested ID lists.
- Abstracts may have multiple `AbstractText` nodes with `Label` and `NlmCategory` attributes.
- Titles, abstracts, and affiliations may contain inline tags, entities, superscripts, italics, or escaped text.
- Dates may be incomplete (`Year` only), textual (`MedlineDate`), season-based, or split across PubMed history fields.
- Author records may be personal, collective, missing initials, or missing affiliations.
- `ArticleIdList` may contain DOI, PMCID, PII, publisher IDs, and other IDs; preserve type.
- XML lists can be absent, singleton, or repeated. Normalize to arrays.
- EFetch XML root elements differ by DB and by error state. Detect `<ERROR>` and warning nodes.
- PMC/JATS XML has namespaces and deeper mixed content; parse separately from PubMed XML.

## Stable normalization fields

All normalized records should include:

```json
{
  "source": "ncbi",
  "source_db": "pubmed",
  "uid": "12345678",
  "identifiers": {
    "pmid": "12345678",
    "pmcid": null,
    "doi": null
  },
  "title": "...",
  "record_type": "article",
  "retrieved_at": "ISO-8601 timestamp",
  "provenance": {
    "endpoint": "efetch",
    "url_path": "efetch.fcgi",
    "retmode": "xml"
  },
  "raw_available": true
}
```

For links, include `source_id`, `target_id`, `target_db`, `link_name`, and provider. For paged searches, include `count`, `retstart`, `retmax`, and history token only when the user asks for reusable history output.

## Source docs

- Entrez Programming Utilities Help: `https://www.ncbi.nlm.nih.gov/books/NBK25501/`
- E-utilities quick start and usage guidelines: `https://www.ncbi.nlm.nih.gov/books/NBK25497/`
- ELink help: `https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.ELink`
- ECitMatch help: `https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.ECitMatch`
