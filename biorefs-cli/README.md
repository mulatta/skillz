# biorefs-cli

Agent-oriented CLI for biomedical literature, NCBI entity lookup, open-access full-text discovery, citations, OpenAlex enrichment, and PubChem compound/assay evidence.

## Goals

- Search and fetch biomedical references from PubMed and PMC.
- Resolve identifiers across PMID, PMCID, DOI, OpenAlex ID, RefSeq accessions, NCBI Gene IDs, and PubChem CIDs/AIDs.
- Retrieve legal PMC full text when structured JATS/XML is available.
- Export references as JSON, Markdown, BibTeX, and RIS.
- Link literature to biomedical entities: genes, transcripts/RNA, proteins, compounds, assays, taxonomy, and related NCBI records.
- Provide a generic NCBI escape hatch without cloning the full EDirect CLI.

## Non-goals

- Reimplement EDirect pipelines such as `esearch | efetch | xtract`.
- Scrape paywalled full text or use Sci-Hub.
- Process local PDFs or infer identifiers from files.
- Make every NCBI database a first-class command at once.
- Replace specialized tools such as BLAST, SRA Toolkit, or cheminformatics suites.

## Commands

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

Commands are synchronous from the user perspective. The shared HTTP layer applies timeouts, retries/backoff, redirect handling, and source-specific rate limits.

## Data sources

| Source | Role |
| --- | --- |
| NCBI E-utilities | PubMed, PMC, Gene, Protein, Nucleotide, taxonomy, links between NCBI databases |
| PMC ID Converter | PMID/PMCID/DOI conversion |
| PMC EFetch | Structured JATS/XML full text where available |
| OpenAlex | DOI/PMID/PMCID mapping, OA location discovery, citation graph, trends |
| Crossref | DOI metadata and BibTeX/RIS fallback |
| PubChem PUG-REST/PUG-View | Compounds, properties, synonyms, xrefs, safety, assays, bioactivity |
| Europe PMC, bioRxiv/medRxiv, Unpaywall, publisher OA pages | Documented fallback references for future deeper full-text support |

## Current command examples

### Setup

```bash
biorefs-cli setup --email user@example.org --timeout-seconds 30
biorefs-cli setup --ncbi-api-key-command 'security find-generic-password -s ncbi -w' --check
```

### Generic NCBI

```bash
biorefs-cli ncbi search --db pubmed --query 'BRCA1[Title/Abstract]' --limit 20 --json
biorefs-cli ncbi fetch --db gene --id 672 --format json
biorefs-cli ncbi summary --db protein --id NP_009225 --json
biorefs-cli ncbi link --dbfrom gene --db pubmed --id 672 --json
```

### Papers

```bash
biorefs-cli paper search 'BRCA1 PARP inhibitor resistance' --source pubmed --limit 50 --json
biorefs-cli paper fetch --pmid 23103855 --include abstract,authors,mesh,grants,ids --json
biorefs-cli paper fulltext --pmcid PMC3525065 --sections methods,results --source auto --json
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
biorefs-cli compound search olaparib --type name
biorefs-cli compound fetch --cid 23725625 --include properties,synonyms,description
biorefs-cli compound xrefs --cid 23725625 --to pubmed,gene,protein
biorefs-cli compound bioactivity --cid 23725625 --active-only
biorefs-cli assay search --target BRCA1
```

### OpenAlex enrichment

```bash
biorefs-cli openalex work --doi 10.1158/2159-8290.cd-12-0049
biorefs-cli openalex graph --doi 10.1158/2159-8290.cd-12-0049 --direction cited-by --limit 50
biorefs-cli openalex oa --doi 10.1158/2159-8290.cd-12-0049
```

## Full-text behavior

Current `paper fulltext` is identifier-first and PMC-focused:

1. Use PMCID directly when provided.
1. Convert PMID/DOI to PMCID with PMC ID Converter when needed.
1. Fetch PMC XML/JATS through NCBI EFetch.
1. Parse body sections, abstract, figures, tables, references, IDs, and license when available.
1. Return structured unavailable or abstract-only metadata when no legal full text is available.

OpenAlex is used for OA discovery/enrichment, not as full-text content. Reference docs describe additional legal fallback APIs, but unsupported sources should return structured unavailable results rather than pretending abstract text is full text.

## Output principles

- Default output is concise Markdown for humans when interactive.
- `--json` returns stable structured records for agents.
- Every claim about a paper or entity should carry identifiers and source provenance.
- Distinguish `metadata-only`, `abstract-only`, and `full-text` evidence.
- Never invent citations. If metadata is incomplete, report missing fields.

## Configuration

Config path:

```text
${XDG_CONFIG_HOME:-~/.config}/biorefs-cli/config.json
```

Config fields:

- `email` for public APIs that accept contact info.
- `ncbi_api_key_command` optional command that prints an NCBI API key to stdout.
- `semantic_scholar_api_key_command` optional command that prints a Semantic Scholar API key to stdout.
- `timeout_seconds` default request and credential-command timeout.

Store API key commands only, never API key values. Do not print secrets or command output used to fetch secrets.

Rate-limit compliance is internal and has no CLI flags. Policies assume configured credentials/keys where services distinguish authenticated and unauthenticated limits.

## Skill docs

The package ships a pi/Claude skill at `skills/SKILL.md` with task-specific reference docs under `skills/references/`. API snapshot files live under `references/api-specs/` and are checked by `tests/test_api_specs.py`.
