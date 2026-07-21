# Graphviz layout

Use `layout` for dependency/topology diagrams, nested groups, dense graphs, or roughly 15 or more nodes. Use direct XML when exact coordinates, sequence-diagram timing, or notation-specific placement matters more than automatic topology.

## Full input schema

```json
{
  "direction": "LR",
  "nodes": [
    {
      "id": "client",
      "label": "Client",
      "style": "rounded=1;whiteSpace=wrap;html=1;",
      "width": 120,
      "height": 60,
      "group": "edge"
    },
    {
      "id": "api",
      "label": "API",
      "width": 140,
      "height": 60,
      "group": "platform/services"
    },
    {
      "id": "db",
      "label": "Database",
      "group": "platform/data"
    }
  ],
  "edges": [
    {
      "id": "client-api",
      "source": "client",
      "target": "api",
      "label": "HTTPS"
    },
    {
      "id": "api-db",
      "source": "api",
      "target": "db",
      "label": "SQL"
    }
  ]
}
```

Run:

```bash
drawio-cli layout graph.json --output candidate.drawio
drawio-cli validate candidate.drawio --strict
```

`--direction TB|LR` overrides the JSON direction. `--dot PATH` overrides the packaged Graphviz executable and is mainly for diagnostics.

## Fields and constraints

### Nodes

- `id` is required, non-empty, and unique. IDs `0` and `1` are reserved.
- `label` defaults to `id`.
- `style` defaults to the built-in rounded service style. Use an exact style from shape search for domain icons.
- `width` and `height` default to 120×60 pixels. Supply positive dimensions suitable for the label/icon.
- `group` is optional. Slash-separated paths create nested groups, for example `platform/data`.
- Group paths cannot have empty segments: `/core`, `core/`, and `core//data` are invalid.

### Edges

- `source` and `target` must reference node IDs.
- `id` is optional; a deterministic source/target-based ID is generated when absent.
- `label` defaults to empty.
- Edge style is the built-in orthogonal style; graph JSON does not expose per-edge style in this version.

Generated XML cell IDs normalize spaces and punctuation to `-`. Inputs such as `api service` and `api-service` therefore collide and are rejected. Node, edge, and generated group IDs share one collision namespace.

## Direction

Use `TB` for:

- process and approval flows
- inheritance trees
- layered pipelines
- top-down decomposition

Use `LR` for:

- request/data paths
- service dependencies
- event pipelines
- client-to-storage architecture

Try one direction first, render, then switch only if hierarchy or labels are materially clearer. Automatic layout cannot know the audience's preferred reading order.

## Groups

A node assigned to `platform/data` becomes a child of nested `data`, which is a child of `platform`. Group geometry is computed bottom-up from direct nodes and child groups. Generated group styles are dashed semantic boundaries.

Keep group paths meaningful. Good examples:

```text
region-a/public
region-a/private
cluster/platform
cluster/workloads
```

Avoid one group per node and decorative nesting. Deep group hierarchies consume title/padding space and can obscure flow.

## Existing documents

`layout` creates a new single-page `.drawio`; it is not a guarded in-place editor. Never point `--output` at an existing document.

To replace one existing page:

```bash
drawio-cli layout graph.json --output candidate.drawio
drawio-cli get-page candidate.drawio --page-index 0 --output candidate.xml
drawio-cli list-pages existing.drawio --json
drawio-cli replace-page existing.drawio \
  --page-name Overview \
  --input candidate.xml \
  --expect-sha256 HASH
```

This preserves other pages and catches Desktop/user changes.

## Output limitations

- One uncompressed page is generated.
- Graphviz selects topology and edge waypoints.
- Coordinates snap to a 10-pixel grid.
- Group colors, custom group styles, ports, and per-edge styles are not graph JSON fields.
- Parallel edge routes depend on Graphviz output and still need visual inspection.
- Sequence, timeline, and notation-specific layouts are not automatically modeled.

After every layout, run strict validation and render a PNG. Inspect node order, group containment, edge crossings, parallel edges, and label clipping before using the output as final.
