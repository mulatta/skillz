# Troubleshooting

## SHA conflict

`replace-page` exits with code 4 when file bytes no longer match `--expect-sha256`.

1. Stop the write.
1. Run `list-pages --json` again.
1. Extract the current target page.
1. Compare user/Desktop changes with the proposed model.
1. Merge deliberately and replace using the new hash.

Do not automatically retry a mutating command with a refreshed hash; that defeats conflict protection.

## Multi-page selector errors

A selector is optional only for a single-page document. For multi-page files provide exactly one of:

```text
--page-id ID
--page-name NAME
--page-index N
```

If names are duplicated or changed, use stable page ID or explicit index after inspecting `list-pages` output. All `drawio-cli` page indices, including `render --page-index`, are zero-based.

## Compressed pages

Desktop may save a diagram page as base64/URI-encoded raw-DEFLATE text. `get-page` decodes it and returns an uncompressed `<mxGraphModel>`. `replace-page` writes the replacement page uncompressed while preserving non-target pages.

Never edit compressed payload text directly. If decoding fails, preserve the source bytes and report the page/document error.

## Validation failure

Run JSON output for exact diagnostics:

```bash
drawio-cli validate diagram.drawio --strict --json
```

Fix errors before warnings. Typical causes:

- duplicate or reserved IDs
- missing parent/source/target
- non-positive geometry
- overlapping siblings
- explicit edge routes crossing nodes or other routes

Do not suppress validator findings. If a warning represents an intentional layout, explain and visually verify it; strict final acceptance still requires correcting the source.

## Missing or weak shape

Try vendor plus resource terms:

```bash
drawio-cli search-shapes "aws lambda" --json
drawio-cli search-shapes "azure function" --json
drawio-cli search-shapes "kubernetes pod" --json
```

Then try `--library` or `--fuzzy`. Inspect `strong`, `kind`, `libraries`, and style before insertion. Never guess an `mxgraph.*` name after search failure.

## Shape index baseline drift

This is expected after nixpkgs changes `pkgs.drawio.src` or when index normalization changes.

Read-only check:

```bash
nix run .#drawio-shape-index.updateScript -- --check
```

The command prints version, hash, registration, capture, and kind-count differences and exits non-zero on drift. Review draw.io version, removed/changed counts, canaries, and representative search results. Then run the updater explicitly:

```bash
nix run .#drawio-shape-index.updateScript
nix build .#drawio-shape-index
nix build .#drawio-cli
```

The updater cannot accept incomplete, remote-resource, or canary-failing candidates. Do not edit the baseline hash manually to bypass generation checks.

## Graphviz layout failure

- Confirm JSON root is an object with `nodes` and optional `edges` lists.
- Confirm every edge endpoint exists.
- Confirm node, edge, and generated group IDs do not normalize to the same XML cell ID.
- Remove empty group path segments.
- Use positive node dimensions and `TB` or `LR` direction.
- Write to a new candidate file, not an existing source document.

If layout succeeds but looks poor, simplify topology, change direction, adjust groups/sizes, and rerender before adding manual XML waypoints.

## Renderer failure or blank export

Rendering uses packaged `drawio-headless`. First run strict validation and preserve the source hash.

- Confirm requested format is `png`, `svg`, or `pdf`.
- Confirm output directory is writable.
- Remove only broken derived output, never source `.drawio`.
- Retry on Linux/Xvfb when Electron/display integration is unreliable.
- Inspect SVG/PDF/PNG output rather than trusting exit status alone.
- Missing icons usually indicate an invalid style or resource, not a reason to fetch a CDN asset.

PNG export repair only restores a missing terminal IEND chunk. It cannot repair arbitrary corrupt image data.

## macOS Keychain access

On macOS, draw.io export launches Electron and may access the user's draw.io profile or login Keychain. `render` preserves the real `HOME` on Darwin so Electron can find the user's unlocked login Keychain. If export fails with a Keychain error, confirm the login Keychain exists, is unlocked, and is visible from the current GUI session, or retry on Linux/Xvfb.

## Desktop ownership recovery

Use Desktop handoff only in a GUI session. The `drawio-cli open FILE` command checks the environment and refuses headless sessions automatically. On macOS it invokes the `drawio` executable directly, not the macOS `open` command.

After handing a file to Desktop with `drawio-cli open FILE`:

1. Stop agent writes.
1. Ask the user to save and close Desktop.
1. Run `list-pages --json` for a new raw-file hash.
1. Inspect the target page again.
1. Resume guarded edits.

There is no supported way to recover or merge Desktop's unsaved in-memory state.
