# biorefs-cli

Agent-oriented CLI for biomedical literature, NCBI entity lookup, open-access full-text discovery, citations, and PubChem compound evidence.

## Goals

- Search and fetch biomedical references from PubMed and PMC.
- Resolve identifiers across PMID, PMCID, DOI, OpenAlex ID, RefSeq accessions, NCBI Gene IDs, and PubChem CIDs.
- Retrieve legal open-access full text from PMC, Europe PMC, bioRxiv/medRxiv, publisher OA links, and OpenAlex-discovered OA locations.
- Export references as JSON, Markdown, BibTeX, and RIS.
- Link literature to biomedical entities: genes, transcripts/RNA, proteins, compounds, assays, taxonomy, and related NCBI records.
- Provide a generic NCBI escape hatch without cloning the full EDirect CLI.

## Non-goals

- Reimplement EDirect pipelines such as `esearch | efetch | xtract`.
- Scrape paywalled full text or use Sci-Hub.
- Make every NCBI database a first-class command at once.
- Replace specialized tools such as BLAST, SRA Toolkit, or full cheminformatics suites.

## Design

The CLI exposes high-level agent-friendly commands backed by direct HTTP API clients. It keeps a small generic NCBI layer for databases that do not yet have polished commands.

```text
biorefs-cli
├── setup       # write config and check credential commands
├── paper       # PubMed, PMC, DOI, citations, related papers, full text
├── gene        # NCBI Gene lookup and links
├── nucleotide  # NCBI Nucleotide / RefSeq RNA/DNA lookup and FASTA
├── protein     # NCBI Protein / RefSeq protein lookup and FASTA
├── compound    # PubChem compounds, xrefs, safety, bioactivity
├── assay       # PubChem BioAssay lookup
├── openalex    # OpenAlex enrichment, OA locations, citation graph
└── ncbi        # generic Entrez search/fetch/summary/link escape hatch
```

Internals should use async HTTP with bounded concurrency, source-specific rate limiting, retries, timeouts, and XDG cache paths. CLI commands stay synchronous from the user perspective.

## Data sources

| Source | Role |
| --- | --- |
| NCBI E-utilities | PubMed, PMC, Gene, Protein, Nucleotide, taxonomy, links between NCBI databases |
| PMC ID Converter | PMID/PMCID/DOI conversion |
| PMC EFetch | Structured JATS full text where available |
| Europe PMC | Biomedical search and OA full-text fallback |
| OpenAlex | DOI/PMID/PMCID mapping, OA locations, citation graph, trends |
| Crossref | DOI metadata and BibTeX/RIS fallback |
| bioRxiv/medRxiv | Preprint metadata and JATS/PDF full-text fallback |
| PubChem PUG-REST/PUG-View | Compounds, properties, synonyms, xrefs, safety, assays, bioactivity |

## API strategy

Use APIs directly rather than depending on EDirect:

- Better JSON/XML parsing control.
- Easier batching, retries, cache, and rate limits.
- Portable Nix packaging.
- Stable machine-readable output for agents.

Provide only minimal Entrez primitives:

```bash
biorefs-cli ncbi search --db pubmed --query 'BRCA1[Title/Abstract]' --limit 20
biorefs-cli ncbi fetch --db gene --id 672 --format json
biorefs-cli ncbi summary --db protein --id NP_009225
biorefs-cli ncbi link --dbfrom gene --db pubmed --id 672
```

## Initial command sketch

### Papers

```bash
biorefs-cli paper search 'BRCA1 PARP inhibitor resistance' --source pubmed --limit 50 --json
biorefs-cli paper fetch --pmid 23103855 --include abstract,authors,mesh,grants,ids --json
biorefs-cli paper fulltext --pmid 23103855 --sections methods,results --source auto --json
biorefs-cli paper related --pmid 23103855 --mode similar --limit 20 --json
biorefs-cli paper cite --pmid 23103855 --format bibtex --strict
biorefs-cli paper convert --doi 10.1158/2159-8290.cd-12-0049 --json
```

### Genes, RNA/transcripts, proteins

```bash
biorefs-cli gene search BRCA1 --taxon human
biorefs-cli gene fetch --gene-id 672 --links pubmed,protein,nucleotide,clinvar
biorefs-cli nucleotide fetch --accession NM_007294 --format fasta
biorefs-cli protein fetch --accession NP_009225 --format fasta
```

### Compounds and assays

```bash
biorefs-cli compound search olaparib
biorefs-cli compound fetch --cid 23725625 --properties --synonyms --xrefs
biorefs-cli compound bioactivity --cid 23725625 --active-only
biorefs-cli assay search --target BRCA1
```

### OpenAlex enrichment

```bash
biorefs-cli openalex work --doi 10.1158/2159-8290.cd-12-0049
biorefs-cli openalex graph --doi 10.1158/2159-8290.cd-12-0049 --direction cited-by --limit 50
biorefs-cli openalex oa --doi 10.1158/2159-8290.cd-12-0049
```

## Full-text resolution order

1. Direct PMCID through PMC EFetch.
1. PMID/DOI to PMCID through PMC ID Converter.
1. Europe PMC fullTextXML.
1. OpenAlex `best_oa_location` / `locations`.
1. bioRxiv/medRxiv JATS or PDF for preprints.
1. Publisher OA landing page/PDF.

Return structured unavailable reasons instead of silent failure:

```json
{
  "status": "unavailable",
  "reason": "no-oa",
  "tried": ["pmc:miss", "europepmc:miss", "openalex:no_oa_location"]
}
```

## Output principles

- Default output should be concise Markdown for humans when interactive.
- `--json` should return stable structured records for agents.
- Every claim about a paper should carry identifiers and source provenance.
- Distinguish abstract-only evidence from full-text evidence.
- Never invent citations. If metadata is incomplete, report missing fields.

## Configuration

Follow XDG Base Directory paths:

```text
$XDG_CONFIG_HOME/biorefs-cli/config.json
$XDG_CACHE_HOME/biorefs-cli/cache.sqlite
$XDG_DATA_HOME/biorefs-cli/
```

Initial setup writes JSON config:

```bash
biorefs-cli setup --email user@example.org --timeout-seconds 30
biorefs-cli setup --ncbi-api-key-command 'security find-generic-password -s ncbi -w' --check
```

Config fields:

- `email` for public APIs that accept contact info.
- `ncbi_api_key_command` optional command that prints an NCBI API key to stdout.
- `semantic_scholar_api_key_command` optional command that prints a Semantic Scholar API key to stdout.
- `timeout_seconds` default request and credential-command timeout.

Store API key commands only, never API key values. Do not print secrets or command output used to fetch secrets.

Rate-limit compliance is internal and has no CLI flags. The shared HTTP layer applies source-specific policies for supported hosts. Policies assume configured credentials/keys where services distinguish authenticated and unauthenticated limits.

## Planned implementation phases

1. PubMed search/fetch, PMID/DOI/PMCID normalization, JSON/Markdown output.
1. PMC full-text extraction and structured unavailable reasons.
1. Citation export via PubMed/Crossref/OpenAlex fallback.
1. Generic NCBI `search/fetch/summary/link` commands.
1. Gene/protein/nucleotide first-class commands.
1. OpenAlex OA/citation enrichment.
1. PubChem compound/assay commands.
1. Europe PMC and bioRxiv/medRxiv full-text fallback.
1. Claude/pi skill under `skills/SKILL.md` with API references under `skills/references/`.

## Skill package plan

This repository ships skills from each tool package. Add later:

```text
biorefs-cli/
├── default.nix
├── pyproject.toml
├── biorefs_cli/
└── skills/
    ├── SKILL.md
    └── references/
        ├── ncbi-entrez.md
        ├── pubmed-pmc.md
        ├── openalex.md
        ├── pubchem.md
        ├── crossref.md
        └── fulltext-fallbacks.md
```

Register in:

- `nix/packages.nix`
- `nix/skills.nix`
- root `README.md`
