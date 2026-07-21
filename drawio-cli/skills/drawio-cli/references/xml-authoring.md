# XML authoring

Author uncompressed XML. `drawio-cli` can read compressed Desktop pages, but editable page input and generated pages should remain reviewable `<mxGraphModel>` XML.

## Document and page structure

A complete single-page file has this shape:

```xml
<mxfile host="offline">
  <diagram id="page-overview" name="Overview">
    <mxGraphModel grid="1" gridSize="10" guides="1" connect="1"
      arrows="1" fold="1" page="1" pageScale="1"
      pageWidth="850" pageHeight="1100" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

Cells `0` and `1` are reserved. Cell `1` is the default layer. Give every other cell a unique, stable semantic ID. Avoid IDs that differ only by spaces and punctuation because generated layouts normalize those characters.

`get-page` returns one standalone `<mxGraphModel>`, not a complete `<mxfile>`. Pass that model to `replace-page`.

## Vertices and edges

A vertex needs `vertex="1"`, a parent, a style, and non-relative geometry:

```xml
<mxCell id="api" value="API" vertex="1" parent="1"
  style="rounded=1;whiteSpace=wrap;html=1;">
  <mxGeometry x="240" y="120" width="120" height="60" as="geometry" />
</mxCell>
```

An edge needs `edge="1"`, valid source and target IDs, and relative geometry:

```xml
<mxCell id="client-api" value="HTTPS" edge="1" parent="1"
  source="client" target="api"
  style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;html=1;">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

Keep auto-routed edges free of guessed waypoints. Add explicit points only when routing must avoid a known obstacle:

```xml
<mxGeometry relative="1" as="geometry">
  <Array as="points">
    <mxPoint x="180" y="150" />
    <mxPoint x="180" y="260" />
  </Array>
</mxGeometry>
```

Explicit routes require visual review because structural validation cannot select the best path.

## Parents, groups, and layers

- Put top-level vertices and edges under layer `1`.
- Represent a container/group as a vertex under its layer or parent container.
- Use `group;` for an invisible container, or `swimlane;startSize=30;` for a titled container.
- Add `pointerEvents=0;` to a custom visual container that should not capture child connections. Omit it when the container itself must be connectable.
- Child geometry is relative to the parent container's origin.
- Keep child coordinates positive and leave room for the parent title band.
- Parent groups must enclose all direct children and nested groups.
- Put an edge crossing different containers on their nearest shared layer, usually `parent="1"`, so neither container clips it.

Example container:

```xml
<mxCell id="backend" value="Backend" vertex="1" parent="1"
  style="swimlane;horizontal=1;startSize=30;rounded=1;html=1;">
  <mxGeometry x="180" y="100" width="360" height="240" as="geometry" />
</mxCell>
<mxCell id="api" value="API" vertex="1" parent="backend"
  style="rounded=1;whiteSpace=wrap;html=1;">
  <mxGeometry x="30" y="60" width="120" height="60" as="geometry" />
</mxCell>
```

## Labels, metadata, and escaping

- XML-escape `&`, `<`, `>`, and attribute quotes.
- Match labels to the user's language.
- Keep labels short. Use `&#xa;` for plain line breaks or escaped `&lt;br&gt;` with `html=1`; a literal `\n` renders as text.
- Use `fontStyle=1`, `2`, or `4` for whole-label bold, italic, or underline. Use escaped HTML only for partial formatting.
- Put protocols or relationship names on edges; do not repeat both endpoint names.
- Use `UserObject` or `object` only when links, tags, or custom metadata are required. Keep the wrapper ID unique and let its child `mxCell` carry geometry/style.
- Do not emit XML comments. Never embed executable HTML, external scripts, remote image URLs, or XML entities.

Example linked object:

```xml
<UserObject id="docs" label="Runbook" link="runbook.md">
  <mxCell vertex="1" parent="1" style="rounded=1;whiteSpace=wrap;html=1;">
    <mxGeometry x="80" y="400" width="120" height="50" as="geometry" />
  </mxCell>
</UserObject>
```

Prefer plain labels when metadata is unnecessary. For a link to another page, use draw.io's page-link form such as `link="data:page/id,page-id"` only after confirming the target page ID.

## Layers, tags, and placeholders

Add a layer as a non-vertex cell under root `0`, then parent ordinary cells to that layer:

```xml
<mxCell id="annotations" value="Annotations" parent="0" />
```

Later layers render above earlier layers. Set `visible="0"` only when a layer should start hidden. Use layers for independently toggleable structural views, not as a replacement for visual containers.

Tags and structured metadata require an `object`/`UserObject` wrapper. Tags are space-separated, and visible text moves from the child cell's `value` to wrapper `label`:

```xml
<object id="auth" label="Auth Service" tags="critical backend"
  placeholders="1" owner="Platform" status="Active">
  <mxCell vertex="1" parent="1"
    style="rounded=1;whiteSpace=wrap;html=1;">
    <mxGeometry x="80" y="300" width="140" height="60" as="geometry" />
  </mxCell>
</object>
```

With `placeholders="1"`, `%owner%` and other wrapper properties can appear in labels. Prefer explicit text unless metadata will be inspected or reused; placeholders add indirection and require visual verification.

## Page sizing and adaptive colors

Set `pageWidth` and `pageHeight` large enough to contain all top-level content with margin. `dx` and `dy` describe editor viewport state, not reliable content bounds. Use 10-pixel grid coordinates where practical; validation warns about off-grid and negative geometry.

Add `adaptiveColors="auto"` to `mxGraphModel` when theme-aware rendering matters. Omitted/default stroke, fill, and font colors adapt most reliably. Explicit colors are transformed by draw.io; inspect both themes when dark mode is a deliverable requirement.

Do not solve a crowded diagram only by enlarging the page. First reduce labels, group related nodes, change direction, or split content into pages.

## Existing-file edit loop

```bash
drawio-cli list-pages diagram.drawio --json
drawio-cli get-page diagram.drawio --page-name Overview --output page.xml
# Edit page.xml and retain HASH from list-pages output.
drawio-cli replace-page diagram.drawio \
  --page-name Overview \
  --input page.xml \
  --expect-sha256 HASH
drawio-cli validate diagram.drawio --strict
```

A selector is required for multi-page documents. Use only one of `--page-id`, `--page-name`, or `--page-index`.

If `replace-page` reports a SHA conflict, do not reuse the replacement immediately. Reload the document, compare the new page with the intended change, and merge deliberately.

## Pre-render checklist

- Reserved cells exist once.
- Every ID is unique.
- Every parent/source/target exists.
- Vertex dimensions are positive.
- Group-relative coordinates stay inside the parent.
- XML attributes and HTML labels are escaped; line breaks are not literal `\n`.
- Non-rectangular generic shapes use an appropriate shape/perimeter style.
- Cross-container edges live on a shared layer.
- No comments, external URLs, or entities exist.
- `validate --strict` succeeds.
