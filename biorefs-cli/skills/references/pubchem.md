# PubChem reference for biorefs-cli

PubChem support lives inside `biorefs-cli` under `compound` and `assay`. Use PubChem for compound, substance, assay, target, safety, xref, and literature evidence. Keep genes, RNA/transcripts, proteins, and PubMed as first-class NCBI/Entrez workflows, then use PubChem cross-references to connect compounds to genes, proteins, pathways, and PubMed.

No API key is required. Do not scrape paywalled pages. Every returned claim should include source/provenance.

## Contents

- [APIs and roles](#apis-and-roles)
- [Compound lookup and search](#compound-lookup-and-search)
- [Compound details and properties](#compound-details-and-properties)
- [PUG-View sections to extract](#pug-view-sections-to-extract)
- [Cross-references](#cross-references)
- [BioAssay and activity](#bioassay-and-activity)
- [Command mapping](#command-mapping)
- [Rate limits, retries, batching, cache](#rate-limits-retries-batching-cache)
- [Output and provenance rules](#output-and-provenance-rules)

## APIs and roles

### PUG-REST

Base endpoint:

```text
https://pubchem.ncbi.nlm.nih.gov/rest/pug
```

Role:

- Identifier lookup and conversion: name, CID, SID, AID, SMILES, InChI, InChIKey, formula.
- Compound properties: formula, weight, SMILES, InChI, XLogP, TPSA, charge, complexity.
- Synonyms and selected cross-references.
- Structure searches: identity, similarity, substructure, superstructure.
- BioAssay summary and concise assay data.
- Bulk-friendly requests using ID lists, POST bodies, and list keys for slower searches.

Common syntax:

```text
/rest/pug/<record-type>/<input>/<operation>/<output>
```

Examples:

```text
/rest/pug/compound/name/olaparib/cids/JSON
/rest/pug/compound/cid/23725625/property/MolecularFormula,MolecularWeight,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,XLogP,TPSA,Charge,Complexity/JSON
/rest/pug/compound/cid/23725625/synonyms/JSON
/rest/pug/compound/cid/23725625/xrefs/PubMedID/JSON
/rest/pug/compound/cid/23725625/assaysummary/JSON
/rest/pug/assay/aid/504526/description/JSON
/rest/pug/assay/aid/504526/concise/JSON
```

Use `JSON` for agent output. Use `CSV` only when an endpoint has better assay tabular coverage and normalize it before returning JSON.

### PUG-View

Base endpoint:

```text
https://pubchem.ncbi.nlm.nih.gov/rest/pug_view
```

Role:

- Human-curated and source-attributed compound and assay sections.
- Descriptions, drug/pharmacology text, mechanism, therapeutic use, safety, GHS hazards, classification, external source links.
- Section/heading navigation when a full PUG-View record is too large.

Examples:

```text
/rest/pug_view/data/compound/23725625/JSON
/rest/pug_view/data/compound/23725625/JSON?heading=Pharmacology%20and%20Biochemistry
/rest/pug_view/data/compound/23725625/JSON?heading=Safety%20and%20Hazards
/rest/pug_view/data/compound/23725625/JSON?heading=Classification
/rest/pug_view/data/assay/504526/JSON
```

PUG-View records are nested sections. Preserve section heading, URL/source, and source name when extracting statements.

## Compound lookup and search

Map `compound search` to PUG-REST lookup/search operations.

Supported inputs:

| User intent | PUG-REST pattern | Notes |
| --- | --- | --- |
| Name lookup | `/compound/name/<name>/cids/JSON` | Return ranked CID candidates with synonyms if available. |
| CID lookup | `/compound/cid/<cid>/property/.../JSON` | Direct fetch path. |
| SMILES lookup | `/compound/smiles/<smiles>/cids/JSON` | URL-encode or POST because SMILES contains special characters. |
| InChI lookup | `/compound/inchi/<inchi>/cids/JSON` | Prefer POST for long InChI strings. |
| InChIKey lookup | `/compound/inchikey/<inchikey>/cids/JSON` | Good exact identifier path. |
| Formula search | `/compound/fastformula/<formula>/cids/JSON` | Formula search can return many hits; always apply `--limit`. |
| 2D similarity | `/compound/fastsimilarity_2d/cid/<cid>/cids/JSON?Threshold=<n>` | Use PubChem defaults unless user requests threshold. |
| 3D similarity | `/compound/fastsimilarity_3d/cid/<cid>/cids/JSON` | Requires 3D conformer availability. |
| Substructure | `/compound/substructure/<input>/cids/JSON` | May require list-key polling for slow jobs. |
| Superstructure | `/compound/superstructure/<input>/cids/JSON` | May require list-key polling for slow jobs. |
| Identity | `/compound/identity/<input>/cids/JSON` | Use for exact normalized structure matching. |

For structure searches, support CID and SMILES first. Add SDF/InChI only when needed. If PubChem returns a list key or delayed job, poll politely with timeout and return an unavailable/timeout status instead of hanging.

## Compound details and properties

Map `compound fetch` to PUG-REST properties, synonyms, PUG-View sections, and optional xrefs.

Recommended property list:

```text
MolecularFormula,MolecularWeight,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,IUPACName,XLogP,TPSA,Charge,Complexity
```

Return normalized fields:

```json
{
  "type": "compound",
  "cid": 23725625,
  "name": "olaparib",
  "molecular_formula": "C24H23FN4O3",
  "molecular_weight": 434.5,
  "canonical_smiles": "...",
  "isomeric_smiles": "...",
  "inchi": "...",
  "inchikey": "...",
  "iupac_name": "...",
  "xlogp": 1.5,
  "tpsa": 86.4,
  "charge": 0,
  "complexity": 760,
  "synonyms": ["olaparib", "AZD2281"],
  "provenance": [
    {
      "source": "PubChem PUG-REST",
      "record_type": "compound",
      "identifier": "CID:23725625",
      "url": "https://pubchem.ncbi.nlm.nih.gov/compound/23725625"
    }
  ]
}
```

Synonyms can be large. Return a concise default list and include total count. Provide an option to request all synonyms.

## PUG-View sections to extract

Map these PUG-View headings into normalized sections. Heading names vary; match case-insensitively and tolerate missing sections.

| Normalized field | PUG-View heading candidates | Notes |
| --- | --- | --- |
| `description` | `Record Description`, `Description` | Short source-attributed description. |
| `pharmacology` | `Pharmacology and Biochemistry`, `Pharmacology` | Include source name and URL. |
| `mechanism` | `Mechanism of Action`, `Drug and Medication Information` | Do not infer mechanism from assay data. |
| `therapeutic_use` | `Therapeutic Uses`, `Drug Indication`, `Use and Manufacturing` | Preserve source. |
| `safety` | `Safety and Hazards`, `Hazards Identification`, `GHS Classification` | Include signal word, hazard statements, precautionary statements when present. |
| `toxicity` | `Toxicity`, `Toxicological Information` | Keep species/route/dose if present. |
| `classification` | `Classification`, `MeSH Pharmacological Classification`, `ChEBI Ontology` | Return source hierarchy and IDs when available. |
| `literature` | `Literature`, `Depositor-Supplied PubMed Citations` | Prefer PubMed IDs as identifiers. |
| `patents` | `Patents` | Keep patent numbers and source. |
| `pathways` | `Biomolecular Interactions and Pathways` | Normalize pathway database and accession. |

PUG-View text can contain depositor-supplied data and third-party source excerpts. Return claims with section/source provenance, not as PubChem-authored facts.

## Cross-references

Map `compound xrefs` to PUG-REST xrefs and PUG-View related-record sections.

Common PUG-REST xref operations:

```text
/rest/pug/compound/cid/<cid>/xrefs/PubMedID/JSON
/rest/pug/compound/cid/<cid>/xrefs/PatentID/JSON
/rest/pug/compound/cid/<cid>/xrefs/GeneID/JSON
/rest/pug/compound/cid/<cid>/xrefs/ProteinGI/JSON
/rest/pug/compound/cid/<cid>/xrefs/RegistryID/JSON
/rest/pug/compound/cid/<cid>/xrefs/RN/JSON
/rest/pug/compound/cid/<cid>/xrefs/SourceName/JSON
/rest/pug/compound/cid/<cid>/xrefs/SourceID/JSON
```

Normalize xrefs:

```json
{
  "type": "xref",
  "subject": {"type": "compound", "cid": 23725625},
  "target": {"type": "pubmed", "pmid": "23103855"},
  "relation": "referenced_in",
  "source": "PubChem PUG-REST",
  "url": "https://pubchem.ncbi.nlm.nih.gov/compound/23725625"
}
```

Expected xref families:

- Literature: PubMed IDs, depositor citations.
- Patents: patent IDs from PUG-REST/PUG-View.
- Genes: NCBI Gene IDs where PubChem records provide them.
- Proteins: PubChem/NCBI protein target identifiers where available; map to NCBI Protein separately when needed.
- Pathways: source database, pathway ID, pathway name from PUG-View.
- External databases: source names and source IDs; do not claim equivalence unless PubChem relation is explicit.

## BioAssay and activity

Map `assay search`, `assay fetch`, and `compound bioactivity` to PubChem BioAssay endpoints.

### AID lookup and assay fetch

Use direct AID fetch when user supplies an AID:

```text
/rest/pug/assay/aid/<aid>/description/JSON
/rest/pug/assay/aid/<aid>/summary/JSON
/rest/pug/assay/aid/<aid>/concise/JSON
/rest/pug_view/data/assay/<aid>/JSON
```

Normalize assay fields:

```json
{
  "type": "assay",
  "aid": 504526,
  "name": "...",
  "description": "...",
  "source_name": "...",
  "assay_type": "confirmatory",
  "targets": [
    {
      "name": "...",
      "gene_id": "...",
      "protein_accession": "...",
      "organism": "..."
    }
  ],
  "provenance": [
    {"source": "PubChem PUG-REST", "identifier": "AID:504526"}
  ]
}
```

### Compound bioactivity

Use compound assay summary first:

```text
/rest/pug/compound/cid/<cid>/assaysummary/JSON
```

For assay-specific rows, fetch concise assay data:

```text
/rest/pug/assay/aid/<aid>/concise/JSON
```

Normalize activity rows:

```json
{
  "type": "bioactivity",
  "cid": 23725625,
  "aid": 504526,
  "outcome": "active",
  "activity_name": "IC50",
  "activity_value": 5.0,
  "activity_unit": "nM",
  "target": {
    "name": "PARP1",
    "gene_id": "142",
    "protein_accession": "..."
  },
  "assay_source": "PubChem BioAssay",
  "provenance": [
    {"source": "PubChem PUG-REST", "identifier": "CID:23725625", "related_identifier": "AID:504526"}
  ]
}
```

Activity names include `IC50`, `EC50`, `Ki`, `Kd`, `AC50`, percent inhibition, and assay-specific readouts. Preserve original PubChem field names alongside normalized fields when available.

For `--active-only`, use PubChem-supported activity filters when an endpoint provides them. Otherwise fetch assay summary/concise rows and filter client-side where normalized `outcome == "active"`. Do not convert inconclusive/unspecified to inactive.

### Assay search

Use `assay search` for these intents:

| User intent | Strategy |
| --- | --- |
| Search by AID | Direct `/assay/aid/<aid>/description/JSON`. |
| Search by compound | `/compound/cid/<cid>/assaysummary/JSON`, then return assays. |
| Search by target gene/protein | Resolve target through NCBI first when possible, then use PubChem target/xref/assay data and PUG-View target sections. |
| Search by text/source | Use PubChem assay endpoints where available; otherwise use NCBI/PubMed search as fallback evidence, clearly labeled. |

## Command mapping

| Command | PubChem calls | Default output |
| --- | --- | --- |
| `compound search <query>` | PUG-REST name/CID/SMILES/InChIKey/formula/structure search to CIDs, then property summary | CID candidates with names, formula, weight, match type. |
| `compound fetch --cid <cid>` | PUG-REST properties + synonyms; optional PUG-View sections | Normalized compound record. |
| `compound fetch --name <name>` | Name to CID, then fetch best CID; include ambiguity if multiple CIDs | Normalized compound record or candidate list. |
| `compound xrefs --cid <cid>` | PUG-REST xrefs + selected PUG-View related sections | Normalized links to PubMed, patents, genes, proteins, pathways, external DBs. |
| `compound bioactivity --cid <cid>` | PUG-REST assay summary; optional assay concise rows | Normalized bioactivity rows. |
| `compound bioactivity --cid <cid> --active-only` | Same as above with supported server filter or client-side active filter | Active rows only; preserve counts before/after filter. |
| `assay search --target <target>` | Resolve target through NCBI; query PubChem assay/target/xref data | Matching AIDs with target and source metadata. |
| `assay search --compound <query>` | Resolve compound to CID; assay summary | AIDs linked to compound. |
| `assay fetch --aid <aid>` | PUG-REST description/summary/concise + PUG-View assay record | Normalized assay record with targets and activity tables as requested. |

## Rate limits, retries, batching, cache

PubChem has no API key but enforces fair-use throttling. Use conservative defaults:

- Use bounded requests and source-specific rate limiting; keep CLI UX synchronous.
- Global PubChem concurrency: 2-4 in-flight requests by default.
- Request rate: stay below 5 requests/second and 400 requests/minute.
- Timeout: 10-30 seconds per request depending on endpoint; longer only for list-key polling with total deadline.
- Retries: exponential backoff with jitter for `429`, `500`, `502`, `503`, `504`, and transient network errors.
- Honor `Retry-After` when present.
- Do not retry non-idempotent POST blindly unless request body is safe and deterministic.
- Cache successful JSON responses under XDG cache with URL/body hash keys.
- Cache negative lookups briefly; do not cache server errors as misses.

Batching guidance:

- Prefer POST for long SMILES/InChI/SDF values and large ID lists.
- Cap property/xref/synonym batches at about 100 CIDs per request by default.
- Cap PUG-View full-record fetches at about 10-25 CIDs/AIDs per batch because records are large.
- For assay concise rows, page/split by AID and stop at user `--limit` when possible.
- For formula/similarity/substructure searches, always apply `--limit`; use list-key polling with total deadline for slow jobs.
- Avoid parallel full PUG-View downloads unless user explicitly requests many records.

## Output and provenance rules

Default Markdown should be concise and cite identifiers. `--json` should be stable and normalized.

Every record should include:

- `source`: `PubChem PUG-REST` or `PubChem PUG-View`.
- `source_url`: API URL or PubChem public record URL.
- `retrieved_at`: UTC timestamp.
- Primary identifier: `cid`, `sid`, or `aid`.
- Original field names for assay/activity values where normalization may lose meaning.
- Section provenance for PUG-View text: heading, source name, source URL when available.

Do not merge PubChem records with NCBI records without preserving identifiers from both sides. Prefer explicit relations:

```json
{
  "compound": {"cid": 23725625},
  "relation": "has_pubchem_xref",
  "target": {"type": "gene", "gene_id": "142"},
  "source": "PubChem PUG-REST"
}
```

Unavailable/error shape:

```json
{
  "status": "unavailable",
  "reason": "pubchem-timeout",
  "tried": ["pug-rest:assaysummary:timeout"],
  "partial": true
}
```

## Source docs

- PUG-REST documentation: <https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest>
- PUG-REST tutorial: <https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest-tutorial>
- PUG-View documentation: <https://pubchem.ncbi.nlm.nih.gov/docs/pug-view>
- PubChem programmatic access overview: <https://pubchem.ncbi.nlm.nih.gov/docs/programmatic-access>
- PubChem identifiers and exchange formats: <https://pubchem.ncbi.nlm.nih.gov/docs/identifiers>
- PubChem BioAssay help: <https://pubchem.ncbi.nlm.nih.gov/docs/bioassays>
