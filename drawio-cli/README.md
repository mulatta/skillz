# drawio-cli

Offline, file-first draw.io authoring helper for agents.

`.drawio` is the source of truth. PNG, SVG, and PDF are derived artifacts. Existing pages are updated with raw-file SHA-256 compare-and-swap so Desktop or user changes are not overwritten silently.

## Commands

- `drawio-cli list-pages FILE.drawio --json`
- `drawio-cli get-page FILE.drawio --page-index 0`
- `drawio-cli replace-page FILE.drawio --input page.xml --expect-sha256 HASH`
- `drawio-cli validate FILE.drawio --strict`
- `drawio-cli search-shapes "aws lambda" --json`
- `drawio-cli layout graph.json --output diagram.drawio`
- `drawio-cli render diagram.drawio --format png --output diagram.png`

Legacy names `pages`, `page-get`, `page-replace`, and `shapes` remain aliases. Commands with structured status support both `-j` and `--json`; data is written to stdout and diagnostics to stderr.

## Exit codes

- `0`: success
- `1`: operational or input-data error
- `2`: command-line usage error
- `3`: valid negative result, such as validation findings or no shape match
- `4`: SHA-256 compare-and-swap conflict

The packaged shape index is generated offline from nixpkgs `pkgs.drawio.src`, stored as deterministic `shape-index.json.gz`, and loaded without runtime network access.

## Rendering

Rendering uses nixpkgs `drawio-headless` by default. On macOS this still launches draw.io's Electron app and may access Keychain, so `render` refuses to run unless `--allow-darwin-render` is passed after user approval. Prefer Linux/Xvfb for automated rendering.

## Shape index maintenance

A nixpkgs draw.io source change that affects the generated index breaks the checked build until its summary is reviewed.

```bash
nix run .#drawio-shape-index.updateScript -- --check
# Review version, hash, registration, capture, and kind-count changes.
nix run .#drawio-shape-index.updateScript
nix build .#drawio-shape-index
nix build .#drawio-cli
```

The updater builds an unchecked candidate only for review. It rejects incomplete factories, failed or remote resources, and missing canaries before changing the committed baseline.

## Licenses

Original repository code is MIT licensed. Adapted material and generated draw.io data retain the terms listed in `THIRD_PARTY_NOTICES.md` and `licenses/`.
