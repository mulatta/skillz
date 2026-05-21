---
name: biorefs-cli
description: Biomedical literature, reference, and entity research helper. Use whenever the user asks for PubMed/PMC/NCBI/Entrez paper search, PMID/PMCID/DOI conversion, biomedical citation/BibTeX/RIS export, legal OA full-text lookup, gene/protein/RNA/transcript evidence, OpenAlex citation/OA enrichment, Semantic Scholar enrichment, PubChem compound/assay/bioactivity lookup, or bio/medical literature review evidence collection.
---

# biorefs-cli

Use `biorefs-cli` workflows for biomedical references and connected bio entities. Prefer stable identifiers and source provenance over broad web search.

Current package implements identifier-first paper, NCBI entity, OpenAlex, PubChem compound/assay, and generic NCBI commands. Use API references for details, fallback policy, and fields not yet exposed by the CLI.

## Core rules

- Prefer PubMed/NCBI for biomedical source-of-record metadata.
- Use APIs directly; do not depend on EDirect or clone `esearch | efetch | xtract` pipelines.
- Use OpenAlex for identifier enrichment, OA location discovery, citation graph, and trends. Do not treat OpenAlex as full text.
- Use PubChem inside this workflow for compounds, assays, xrefs, safety, and bioactivity; do not split to a separate PubChem skill.
- Retrieve only legal open-access full text. Never use Sci-Hub, credential sharing, paywall bypass, or hidden publisher scraping.
- Distinguish `metadata-only`, `abstract-only`, and `full-text` evidence.
- Never invent citations. Report missing fields and ambiguous matches explicitly.
- Keep every claim tied to PMID, PMCID, DOI, OpenAlex ID, PubChem CID/AID, NCBI Gene ID, accession, and source URL when available.
- Use the CLI/shared clients so source-specific rate limits, retries/backoff, and timeouts apply. Do not flood NCBI or other public APIs.
- Do not print API keys or secret-command output.

## Choose reference docs

Read only the relevant reference file:

| Task | Read |
| --- | --- |
| PubMed/PMC metadata, paper search, PMID/PMCID/DOI, abstracts | `references/pubmed-pmc.md` |
| Generic NCBI Entrez DB search/fetch/link, gene/protein/nucleotide/taxonomy | `references/ncbi-entrez.md` |
| Legal OA full-text resolver, PMC/Europe PMC/bioRxiv/Unpaywall/publisher fallback | `references/fulltext-fallbacks.md` |
| OpenAlex DOI/PMID/PMCID enrichment, OA locations, citation graph, trends | `references/openalex.md` |
| Citation export, Crossref DOI metadata, BibTeX/RIS, deposited references | `references/crossref.md` |
| PubChem compounds, assays, bioactivity, safety, xrefs | `references/pubchem.md` |
| Semantic Scholar optional enrichment: TLDR, influential citations, recommendations | `references/semantic-scholar.md` |

## Default workflows

### Literature search

1. Search PubMed first.
1. Fetch PubMed XML metadata for candidate PMIDs.
1. Normalize IDs: PMID, PMCID, DOI.
1. Enrich with OpenAlex when citation counts, related works, OA locations, authors/institutions, or trends matter.
1. Use Crossref for DOI metadata and citation export fallback.
1. Return ranked table with identifiers, title, year, journal, evidence level, and source provenance.

### Full text

1. Convert PMID/DOI to PMCID with PMC ID Converter.
1. Try PMC EFetch JATS/XML.
1. Try Europe PMC fullTextXML.
1. Use OpenAlex only to find OA candidate URLs.
1. Try bioRxiv/medRxiv JATS/PDF for preprints.
1. Optionally use Unpaywall when email is configured.
1. Follow publisher/repository OA URLs only when access/license is explicit.
1. If none succeeds, return structured unavailable reason; do not substitute abstract as full text.

### Citation export

1. Prefer PubMed metadata when PMID exists.
1. Use Crossref DOI lookup/content negotiation for BibTeX/RIS fallback.
1. Use OpenAlex as enrichment, not citation source of record.
1. Deduplicate by PMID, DOI, PMCID, OpenAlex ID, then high-confidence bibliographic match.
1. Emit missing-field warnings separately.

### Gene, RNA, protein

1. Use NCBI Entrez `gene`, `nuccore`, `protein`, and `taxonomy`.
1. Link across entities with ELink.
1. Link entity evidence to PubMed/PMC records.
1. Fetch FASTA/GenBank only when user asks for sequences.

### Compound/assay

1. Use PubChem PUG-REST for CID/AID lookup, properties, synonyms, xrefs, and assay summaries.
1. Use PUG-View for source-attributed descriptions, safety, pharmacology, mechanisms, therapeutic use, and classification.
1. Link PubChem xrefs to PubMed, genes, proteins, patents, and pathways.
1. Treat assay outcomes and activity values as assay-specific evidence; do not infer mechanism from activity rows alone.

## Expected output shape

For research summaries, use concise Markdown with source-backed claims:

```markdown
## Summary

## Key papers

| Evidence | Year | Finding | IDs |
| --- | --- | --- | --- |
| abstract-only/full-text | YYYY | claim | PMID, DOI, PMCID |

## Entity links

## Full-text availability

## Missing or ambiguous items
```

For machine-readable output, use stable JSON with:

- `identifiers`
- `title` or entity name
- `evidence_level`
- `sources` / `provenance`
- `warnings`
- `missing`
- `tried` for unavailable full text or failed conversions

## Current CLI commands

Generic NCBI commands:

```bash
biorefs-cli ncbi search --db pubmed --query 'BRCA1[Title/Abstract]' --limit 20 --json
biorefs-cli ncbi summary --db gene --id 672 --json
biorefs-cli ncbi fetch --db protein --id NP_009225 --format fasta --raw
biorefs-cli ncbi link --dbfrom gene --db pubmed --id 672 --json
```

Higher-level commands:

```bash
biorefs-cli paper search 'BRCA1 PARP inhibitor resistance' --limit 50 --json
biorefs-cli paper fetch --pmid 23103855 --json
biorefs-cli paper fulltext --pmid 23103855 --sections methods,results
biorefs-cli paper related --pmid 23103855 --mode similar --limit 20
biorefs-cli paper cite --pmid 23103855 --format bibtex
biorefs-cli paper convert --doi 10.1158/2159-8290.cd-12-0049

biorefs-cli gene search BRCA1 --taxon human
biorefs-cli gene fetch --gene-id 672 --links pubmed,protein,nucleotide,clinvar
biorefs-cli nucleotide fetch --accession NM_007294 --format fasta
biorefs-cli protein fetch --accession NP_009225 --format fasta

biorefs-cli compound search olaparib --type name
biorefs-cli compound fetch --cid 23725625 --include properties,synonyms,description
biorefs-cli compound xrefs --cid 23725625 --to pubmed,gene,protein
biorefs-cli compound bioactivity --cid 23725625 --active-only
biorefs-cli assay search --target BRCA1
```

## Deferred beyond MVP

Keep these out of default context unless the user asks for deeper implementation planning:

- Persistent XDG cache for API responses and identifier normalization.
- More uniform JSON schema across every command.
- Europe PMC fullTextXML and publisher OA HTML/JATS retrieval beyond current PMC-first path.
- Batch DOI/PMID/CID/Gene workflows with bounded concurrency.
- Semantic Scholar CLI commands for TLDR, recommendations, influential citations, and citation contexts.
- Cross-entity evidence graph linking papers, genes, proteins, compounds, assays, and PubMed evidence.
- Broader recorded fixtures for malformed/partial API responses.
