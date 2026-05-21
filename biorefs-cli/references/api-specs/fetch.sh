#!/usr/bin/env bash
set -euo pipefail

out_dir="${1:-$(dirname "$0")/raw}"
mkdir -p "$out_dir"

curl_common=(
  --fail
  --location
  --show-error
  --silent
  --retry 3
  --retry-delay 1
  --connect-timeout 10
  --max-time 60
  --user-agent "biorefs-cli-spec-fetch/0.1"
)

fetch() {
  local url="$1"
  local output="$2"
  printf 'fetch %s -> %s\n' "$url" "$output" >&2
  curl "${curl_common[@]}" "$url" -o "$out_dir/$output"
}

fetch "https://docs.openalex.org/api-reference/openapi.json" \
  "openalex-openapi.json"
fetch "https://api.semanticscholar.org/graph/v1/swagger.json" \
  "semantic-scholar-graph-v1-swagger.json"
fetch "https://api.semanticscholar.org/recommendations/v1/swagger.json" \
  "semantic-scholar-recommendations-v1-swagger.json"
fetch "https://api.semanticscholar.org/datasets/v1/swagger.json" \
  "semantic-scholar-datasets-v1-swagger.json"
fetch "https://www.ebi.ac.uk/europepmc/webservices/api/swagger.json" \
  "europepmc-swagger.json"
fetch "https://api.crossref.org/swagger-docs" \
  "crossref-swagger-docs.json"
fetch "https://www.ncbi.nlm.nih.gov/datasets/docs/v2/openapi3/openapi3.docs.yaml" \
  "ncbi-datasets-openapi3.docs.yaml"

# Upstream YAML contains trailing whitespace; normalize it so `git diff --check`
# stays useful for generated snapshots.
yaml_file="$out_dir/ncbi-datasets-openapi3.docs.yaml"
tmp_file="$(mktemp)"
awk '{ sub(/[[:space:]]+$/, ""); print }' "$yaml_file" >"$tmp_file"
mv "$tmp_file" "$yaml_file"
