# RCSB PDB and AlphaFold structure reference

Operational notes for the `biorefs-cli structure` commands. These complete the
protein workflow: `uniprot fetch` emits PDB cross-reference pointers, and the
`structure` commands resolve them to ranked search results, metadata, and
coordinate files. Retrieval only — no structural analysis (alignment, SASA,
secondary structure, folding); those belong to dedicated structural-biology
tooling outside this skill.

## Endpoints

| Endpoint | URL | Use |
| --- | --- | --- |
| Search | `https://search.rcsb.org/rcsbsearch/v2/query` (POST) | Full-text, sequence, attribute search; returns ids + score |
| Data (REST) | `https://data.rcsb.org/rest/v1/core/entry/{id}` | Per-entry metadata; `polymer_entity/{id}/{n}` for organism/UniProt |
| Data (GraphQL) | `https://data.rcsb.org/graphql` (POST) | One-call batch enrichment of a page of hits |
| Files | `https://files.rcsb.org/download/{id}.cif` | mmCIF/PDB coordinates; `{id}-assembly{N}.cif` for assemblies |
| AlphaFold | `https://alphafold.ebi.ac.uk/api/prediction/{acc}` | Predicted-model metadata + file URLs (AlphaFold2, precomputed) |

All keyless. Send a `User-Agent` (EBI rejects anonymous requests with HTTP 403).
The client maps these hosts to the `rcsb` / `alphafold` rate-limit policies.

## `structure search`

```bash
biorefs-cli structure search "BRCA1 BRCT domain" --limit 10
biorefs-cli structure search --uniprot P38398 --method xray --max-resolution 2.5
biorefs-cli structure search --sequence-file query.fasta --organism 9606
biorefs-cli structure search "kinase" --limit 25 --offset 25
```

- Exactly one primary input: positional full-text, `--sequence`/`--sequence-file`
  (RCSB mmseqs2 sequence search), or `--uniprot ACC`.
- Filters compose with AND: `--method {xray,nmr,em,cryoem}`, `--max-resolution`,
  `--organism TAXID`. Page with `--offset`.
- Results are enriched in one GraphQL batch call: each hit carries `pdb_id`,
  `score`, `method`, `resolution`, `organisms`, `title`. If enrichment fails the
  command degrades to bare ids plus a warning rather than failing.

## `structure fetch`

```bash
biorefs-cli structure fetch 1JM7                  # -> ./1jm7.cif (mmCIF)
biorefs-cli structure fetch 1JM7 --format pdb --out-dir ~/structures
biorefs-cli structure fetch 1JM7 --assembly 1     # biological assembly, not asym unit
biorefs-cli structure fetch --uniprot P38398      # AlphaFold model (AF2)
```

- `--assembly N` downloads a biological assembly instead of the asymmetric unit —
  important when the biological unit differs from the deposited coordinates (a
  dimer deposited as a monomer, etc.). Applies to PDB ids only, not AlphaFold.
- `--out-dir DIR` chooses the directory (default: cwd); `--output PATH` pins an
  exact output file path, overriding `--out-dir` and the default name.
- Writes the file and prints its path; `--json` adds source, url, bytes, path.

## `structure info`

```bash
biorefs-cli structure info 1JM7
biorefs-cli structure info 1T15 1JM7 3FA2          # batch
biorefs-cli structure info 1JM7 --include entities  # organism + UniProt xref
```

- Returns title, method, resolution, deposit date, ligands, and chain count.
- `--include entities` adds per-entity organism and UniProt cross-references —
  the link back to `uniprot`. Multiple ids return one record each.

## Notes

- PDB ids: classic 4-character (`1abc`) and the extended `pdb_0000XXXX` form.
- AlphaFold DB is a precomputed AlphaFold2 lookup keyed by UniProt accession, not
  an on-demand folding service; novel-sequence prediction is out of scope.
- Resolution is null for methods without one (NMR).

## Source docs

- RCSB Search API: `https://search.rcsb.org/#search-api`
- RCSB Data API: `https://data.rcsb.org/`
- AlphaFold DB API: `https://alphafold.ebi.ac.uk/api-docs`
