# Shape search

Search the packaged offline index for domain-specific symbols: AWS, Azure, GCP, Kubernetes, Cisco/network, P&ID, electrical, and branded/product resources.

Skip search for standard rectangles, rounded boxes, diamonds, ellipses, cylinders, text, generic containers, and ordinary arrows. See `style-reference.md` for those styles.

## Search behavior

```bash
drawio-cli search-shapes "aws lambda" --json
drawio-cli search-shapes "kubernetes pod" --kind vertex --limit 5 --json
drawio-cli search-shapes "router" --library cisco --limit 10 --json
```

Queries split whitespace, camelCase, and letter/digit boundaries. Default search requires every term to match either an exact token or its Soundex code. Results rank exact hits above phonetic hits.

JSON output contains top-level match quality:

```json
{
  "strong": true,
  "results": []
}
```

Treat `strong: true` as preferred. `strong: false` can mean every term matched only partly/phoneticly; inspect title, library, style, and dimensions before use.

`--fuzzy` allows scored OR fallback when no all-term result exists. Use it only after a specific exact query fails. Never select the first fuzzy result without semantic inspection.

Improve weak queries in this order:

1. Add vendor/library context: `lambda` → `aws lambda`.
1. Try official product wording or a shorter resource noun.
1. Filter a known library with `--library`.
1. Use `--fuzzy`, then inspect multiple results.

A no-result command exits non-zero; do not silently replace a missing official symbol with a guessed `mxgraph.*` style.

## Result fields

Each result contains:

- `id`: stable content-derived identifier.
- `kind`: `vertex`, `edge`, or `template`.
- `title`: display/search title.
- `tags`: normalized search tokens.
- `libraries`: draw.io libraries that registered the item.
- `style`: exact single-cell style when representable.
- `width`, `height`: default dimensions.
- `templateXml`: serialized cells for composite templates, otherwise null.

For a single-cell result, copy `style` exactly. Use returned dimensions for vertices; edge dimensions may be zero and are not placement geometry. Change label, position, parent, and semantic ID without rewriting shape-specific style keys.

## Composite templates

A `template` may contain multiple cells, nested parents, labels, and edges. Its `templateXml` cannot be reduced to one style without losing structure.

This CLI does not provide automatic template instantiation. Safest options:

1. Search for a semantically equivalent single-cell vertex.
1. Build the concept from generic cells.
1. Insert the template manually only when necessary, rewriting every inserted ID and internal reference, assigning the intended parent, and then running strict validation and visual review.

Do not paste template cells with their original IDs into an existing page. Duplicate IDs can corrupt unrelated edges and parents.

## Offline and provenance guarantees

- Index is generated from the same nixpkgs `pkgs.drawio.src` version used for packaging.
- Builder captures draw.io `Sidebar.addEntry` registrations and `createItem` cells.
- Remote requests, missing local resources, incomplete factories, and canary failures stop the build.
- Runtime reads the packaged `shape-index.json.gz`; it performs no network request.
- Shape entries containing remote image resources are rejected during index generation.

When nixpkgs changes draw.io source, baseline checks intentionally fail until the generated manifest is reviewed and updater is run.
