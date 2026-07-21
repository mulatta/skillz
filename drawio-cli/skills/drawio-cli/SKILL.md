---
name: drawio-cli
description: Create, inspect, edit, validate, lay out, render, and hand off draw.io diagrams using local .drawio files and the offline drawio-cli. Use whenever the user asks for architecture diagrams, flowcharts, UML, ERD, network/cloud/Kubernetes diagrams, process maps, edits to .drawio files, or PNG/SVG/PDF exports from draw.io, even when they do not explicitly ask for draw.io tooling.
---

# drawio-cli workflow

Use `drawio-cli` for file-first draw.io work. Keep `.drawio` as source of truth; treat PNG, SVG, and PDF as derived artifacts.

## Protect existing work

- Inspect an existing document with `drawio-cli list-pages FILE --json`, then extract the target page with `get-page`.
- Preserve the SHA-256 returned by `list-pages`. Replace an existing page only with `replace-page --expect-sha256 HASH`.
- Stop after a SHA conflict. Reload and inspect the user's changes instead of retrying with a new hash blindly.
- Do not edit a file while draw.io Desktop has it open. After Desktop handoff, wait for the user to save and close it before taking a new hash.
- Preserve every non-target page and keep the source `.drawio` after export.
- Avoid external image URLs, icon CDNs, and browser-hosted draw.io services. Runtime work must remain offline.

## Choose an authoring route

Use direct uncompressed XML for small diagrams, precise placement, or focused edits. Read `references/xml-authoring.md` and `references/style-reference.md` before writing unfamiliar cells or styles.

Use graph JSON plus `layout` for dependency/topology diagrams, nested groups, dense graphs, or roughly 15 or more nodes. Read `references/layout.md` for its complete schema and constraints.

Search official local shapes before using cloud, Kubernetes, network, P&ID, electrical, or branded symbols. Generic flowcharts, UML, and ERD usually need only standard styles. Read `references/shape-search.md` before handling composite templates.

Use `references/diagram-patterns.md` to select direction, grouping, shapes, and edge semantics for an unfamiliar diagram type.

## Create a new document

1. Identify diagram purpose, audience, label language, required content, and requested export formats. Match labels to the user's language.
1. Choose direct XML or graph layout.
1. Search domain shapes when needed; never guess an `mxgraph.*` style.
1. Write a new `.drawio`, keeping authored pages uncompressed.
1. Run `drawio-cli validate FILE --strict`.
1. Render a draft PNG where the platform permits it.
1. Inspect the image using `references/visual-review.md`; fix structure or layout and repeat.
1. Produce requested final exports while preserving the `.drawio` source.

## Modify an existing document

```bash
drawio-cli list-pages diagram.drawio --json
drawio-cli get-page diagram.drawio --page-index 0 --output page.xml
# Edit page.xml as one mxGraphModel; keep HASH from list-pages output.
drawio-cli replace-page diagram.drawio \
  --page-index 0 \
  --input page.xml \
  --expect-sha256 HASH
drawio-cli validate diagram.drawio --strict
```

For a layout-generated replacement, generate a separate candidate file first. Extract its page model, then install that model with guarded `replace-page`; never run `layout --output` directly over an existing document.

```bash
drawio-cli layout graph.json --output candidate.drawio
drawio-cli get-page candidate.drawio --page-index 0 --output candidate.xml
drawio-cli replace-page diagram.drawio \
  --page-name Overview \
  --input candidate.xml \
  --expect-sha256 HASH
```

## Validate and review every iteration

Run structural validation before rendering. A clean validator catches broken references and geometry defects but does not prove visual quality. Render a PNG draft and inspect clipping, overlap, edge crossings, label readability, hierarchy, and icon consistency.

```bash
drawio-cli validate diagram.drawio --strict
drawio-cli render diagram.drawio --format png --width 2000 --output diagram-preview.png
```

On macOS, `render` is blocked because draw.io export launches Electron and may access Keychain. Prefer Linux/Xvfb. Pass `--allow-darwin-render` only after explicit user approval.

## Finish and hand off

- Validate the final source and inspect the final render.
- Return the `.drawio` plus requested PNG/SVG/PDF exports.
- State which file is source of truth.
- If the user opens the file in Desktop, relinquish agent ownership until they save and close it.
- Do not promise live co-edit, unsaved Desktop recovery, browser editing, importers, or automatic composite-template insertion; this skill does not provide them.

## Command summary

```bash
drawio-cli list-pages FILE --json
drawio-cli get-page FILE --page-id ID --output page.xml
drawio-cli replace-page FILE --page-id ID --input page.xml --expect-sha256 HASH
drawio-cli validate FILE --strict --json
drawio-cli search-shapes "aws lambda" --kind vertex --json
drawio-cli layout graph.json --output diagram.drawio --direction LR
drawio-cli render diagram.drawio --format png --output diagram.png
```

## References

Read only what the task needs:

- `references/xml-authoring.md` — page, cell, parent, geometry, metadata, and safe replacement rules.
- `references/style-reference.md` — standard vertex, container, text, and edge styles.
- `references/diagram-patterns.md` — architecture, process, UML, ERD, cloud/network, and industrial patterns.
- `references/shape-search.md` — exact/fuzzy search, filters, shape kinds, and template limits.
- `references/layout.md` — graph JSON schema, direction, groups, and generated-ID constraints.
- `references/visual-review.md` — required visual QA after rendering.
- `references/troubleshooting.md` — conflicts, compressed pages, index drift, Graphviz, and renderer failures.
