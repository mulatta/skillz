# API specs

Fetched OpenAPI/Swagger specs for APIs that publish machine-readable descriptions.

Last fetched: 2026-05-21.

## Fetched specs

- `raw/openalex-openapi.json` — OpenAPI 3.1.0 — OpenAlex API — 43 paths
- `raw/semantic-scholar-graph-v1-swagger.json` — Swagger 2.0 — Academic Graph API — 14 paths
- `raw/semantic-scholar-recommendations-v1-swagger.json` — Swagger 2.0 — Recommendations API — 2 paths
- `raw/semantic-scholar-datasets-v1-swagger.json` — Swagger 2.0 — S2AG Datasets — 4 paths
- `raw/europepmc-swagger.json` — Swagger 2.0 — Europe PMC Web Service — 16 paths
- `raw/crossref-swagger-docs.json` — Swagger 2.0 — Crossref REST API — 18 paths
- `raw/ncbi-datasets-openapi3.docs.yaml` — OpenAPI 3.0.1 — NCBI Datasets API — about 107 paths

## Source URLs

| File | Source URL |
| --- | --- |
| `openalex-openapi.json` | `https://docs.openalex.org/api-reference/openapi.json` |
| `semantic-scholar-graph-v1-swagger.json` | `https://api.semanticscholar.org/graph/v1/swagger.json` |
| `semantic-scholar-recommendations-v1-swagger.json` | `https://api.semanticscholar.org/recommendations/v1/swagger.json` |
| `semantic-scholar-datasets-v1-swagger.json` | `https://api.semanticscholar.org/datasets/v1/swagger.json` |
| `europepmc-swagger.json` | `https://www.ebi.ac.uk/europepmc/webservices/api/swagger.json` |
| `crossref-swagger-docs.json` | `https://api.crossref.org/swagger-docs` |
| `ncbi-datasets-openapi3.docs.yaml` | `https://www.ncbi.nlm.nih.gov/datasets/docs/v2/openapi3/openapi3.docs.yaml` |

Run `./fetch.sh` from this directory to refresh.

Run the API spec consistency test from the repository root:

```bash
pytest biorefs-cli/tests/test_api_specs.py
```

## APIs without useful Swagger/OpenAPI found

These still need hand-written reference notes:

- NCBI E-utilities / Entrez (`esearch`, `efetch`, `esummary`, `elink`, `epost`, `espell`, `ecitmatch`). Official docs exist, but no OpenAPI spec found.
- PMC EFetch and PMC ID Converter. Docs exist, but no OpenAPI spec found.
- PubChem PUG-REST and PUG-View. Docs exist, but no OpenAPI spec found at common `swagger.json` / `openapi.json` locations.
- bioRxiv/medRxiv API. Docs exist, but no OpenAPI spec found.
- Unpaywall API. Docs exist, but no OpenAPI spec fetched yet.

## Notes

NCBI Datasets API is not a replacement for Entrez. Keep it as a reference for genome/gene/dataset-style endpoints; PubMed/PMC workflows still use E-utilities and PMC-specific endpoints.
