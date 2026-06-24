# UniProtKB reference

Operational notes for the `biorefs-cli uniprot` command. UniProt is the
identifier-first protein hub: it resolves a protein name or gene to a canonical
accession, curated function, entity cross-references, and the literature that
supports each annotation. Use it to connect papers, genes, and proteins; do not
use it for 3D structure files.

## Scope and boundary

- In scope: canonical accession/entry name, reviewed (Swiss-Prot) vs unreviewed
  (TrEMBL) status, protein/gene names, organism, length, function, sequence
  (FASTA), entity cross-references (GeneID, RefSeq, Ensembl), and curated
  literature PMIDs.
- Out of scope here: 3D coordinates, structural alignment, ligands, docking,
  model building. UniProt surfaces PDB cross-references as **pointers only** (PDB
  id, method, resolution, chains). Resolve those ids to search results, metadata,
  or coordinate files with the `structure` commands (see `references/structure.md`).
  Structural analysis (alignment, SASA, folding) is out of scope for the whole skill.
- UniProt accessions are the seam: `uniprot fetch` emits PDB ids, NCBI GeneID,
  and RefSeq accessions; the `structure`, `gene`, `protein`, and `nucleotide`
  commands consume them.

## Base URL and endpoints

Base URL:

```text
https://rest.uniprot.org
```

| Endpoint | Path | Use |
| --- | --- | --- |
| Search | `/uniprotkb/search?query=...&format=json&fields=...&size=N` | Find entries by free text or field query. |
| Entry | `/uniprotkb/{accession}?format=json&fields=...` | Fetch one entry's annotation. |
| FASTA | `/uniprotkb/{accession}.fasta` | Canonical sequence passthrough. |

Always send a descriptive `User-Agent`. Request only the `fields` needed; the
full entry JSON is large. The client maps `rest.uniprot.org` to the `uniprot`
rate-limit policy (5 req/s, 200 req/min) — do not bypass it.

## Query syntax

`uniprot search QUERY` passes QUERY straight into the UniProt query string, then
appends filters:

- `--taxon TAXID` -> `AND organism_id:TAXID` (numeric NCBI taxonomy id only).
- `--reviewed` -> `AND reviewed:true` (Swiss-Prot only; prefer for curated work).

Useful field queries to pass as QUERY:

- `gene:BRCA1` exact gene symbol.
- `protein_name:"breast cancer"` protein name phrase.
- `accession:P38398` direct accession.
- `xref:pdb-1JM7` entries linked to a PDB structure.

## Field selection

The CLI requests a core field set always, plus extra fields per `--include`
section (default: all sections):

| `--include` | UniProt fields | Output key |
| --- | --- | --- |
| (core) | `accession,id,reviewed,protein_name,gene_names,organism_name,organism_id,length` | `accession,entry_name,reviewed,protein_name,genes,organism,tax_id,length` |
| `function` | `cc_function` | `function` (list of text) |
| `xrefs` | `xref_pdb,xref_geneid,xref_refseq,xref_ensembl` | `pdb` (pointers), `xrefs` (GeneID/RefSeq/Ensembl) |
| `literature` | `lit_pubmed_id` | `literature_pmids` (deduped) |

Optional output keys are omitted when empty.

## Linking workflows

### Paper -> related proteins

1. From a paper, extract gene symbols or protein names.
1. `uniprot search gene:SYMBOL --taxon 9606 --reviewed` to get canonical
   accessions and protein names.
1. For deeper evidence, `uniprot fetch --accession ACC` and follow
   `literature_pmids` into `paper`/`ncbi` commands.

### Protein -> related research

1. `uniprot fetch --accession ACC --include literature,xrefs`.
1. `literature_pmids` are the curated references; resolve with
   `paper fetch --pmid` or `ncbi summary --db pubmed`.
1. `xrefs.GeneID` links to `gene fetch --gene-id`; `xrefs.RefSeq` links to
   `protein fetch`/`nucleotide fetch` for sequence-of-record records.

### Protein -> structure (handoff)

1. `uniprot fetch --accession ACC --include xrefs` returns `pdb` pointers
   (`id`, `method`, `resolution`, `chains`).
1. Pass the PDB id to the `structure` commands — `structure info <id>` for
   metadata, `structure fetch <id>` for the coordinate file, or `structure search --uniprot ACC` to rank all structures for the protein. When only the ids
   matter, the pointers are already a complete answer.

## Division of labor with NCBI

UniProt and NCBI Entrez `protein` overlap on sequence and gene links. Split by
role:

- UniProt: canonical, manually curated identity; function; cross-reference hub;
  reviewed vs unreviewed distinction.
- NCBI `protein`/`nuccore`: RefSeq/GenBank source-of-record records and FASTA;
  `ELink` traversal across Entrez databases.

Prefer UniProt to name a protein and to enumerate its cross-references; prefer
NCBI to pull a specific RefSeq record or to traverse Entrez links. This mirrors
how PubChem coexists with NCBI inside this skill.

## Parsing notes

- `entryType` carries review status: `UniProtKB reviewed (Swiss-Prot)` vs
  `UniProtKB unreviewed (TrEMBL)`.
- Protein name precedence: `proteinDescription.recommendedName.fullName.value`,
  then `submissionNames`, then `alternativeNames` (TrEMBL entries often lack a
  recommended name).
- Function text lives in `comments[]` where `commentType == "FUNCTION"`, under
  `texts[].value`.
- PDB/GeneID/RefSeq/Ensembl live in `uniProtKBCrossReferences[]` keyed by
  `database`; PDB detail is in `properties[]` (`Method`, `Resolution`,
  `Chains`); a `Resolution` of `-` means none (e.g. NMR).
- Literature PMIDs come from `references[].citation.citationCrossReferences[]`
  where `database == "PubMed"`; the same PMID can repeat across references, so
  dedupe.
- Cross-reference lists (RefSeq/Ensembl isoforms) can be long; this is real
  data, not truncated.

## Source docs

- UniProt REST API: `https://www.uniprot.org/help/api`
- Query fields: `https://www.uniprot.org/help/query-fields`
- Return fields: `https://www.uniprot.org/help/return_fields`
- Programmatic access: `https://www.uniprot.org/help/programmatic_access`
