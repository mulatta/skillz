# Visual review

Structural validation is necessary but not sufficient. It can detect malformed references, invalid geometry, overlap candidates, and route defects; it cannot judge hierarchy, reading order, notation, or whether labels are understandable.

Render a PNG draft after each meaningful change, inspect it as an image, and modify the `.drawio` source rather than the export.

## Review order

### 1. Purpose and hierarchy

- Can the intended audience identify the diagram's subject immediately?
- Is the main flow readable in the chosen `TB` or `LR` direction?
- Are primary systems/actions visually stronger than annotations and boundaries?
- Do page title, group names, and node labels use consistent terminology?
- Is detail appropriate for one audience and one level of abstraction?

Split pages when overview and implementation details compete.

### 2. Geometry

- No node, group title, or label is clipped.
- Sibling nodes do not overlap.
- Children sit fully inside containers with padding.
- Nested groups are visibly distinct and not the same size/position.
- Page bounds include all content with margin.
- Nodes have consistent dimensions unless size conveys meaning.

Validation warnings are prompts to inspect, not permission to ignore visible defects.

### 3. Edges

- Edges connect the intended endpoints.
- Arrow direction matches the described flow or dependency.
- Decision branches and relationship types are labelled where ambiguous.
- Routes do not pass through unrelated nodes or labels.
- Crossings and long backtracking paths are minimized.
- Parallel edges remain distinguishable.
- Dashed, open-arrow, and solid styles have one consistent meaning.

If Graphviz produces a confusing route, adjust topology/grouping/direction before adding many manual waypoints.

### 4. Text

- Labels remain readable at normal preview size.
- Names are concise and avoid implementation prose.
- Edge labels use protocol, event, condition, or cardinality—not redundant endpoint names.
- Font sizes and alignment are consistent.
- Escaped characters display as intended rather than raw XML/HTML.

### 5. Shapes and color

- Domain icons come from one coherent library/version.
- Generic and official shapes are not mixed arbitrarily.
- Color encodes a stable category or status.
- Meaning does not depend on color alone.
- Text/background contrast remains readable.
- No missing-image placeholder or network-dependent asset appears.

### 6. Deliverables

- Final `.drawio` validates strictly.
- Final export matches the reviewed source revision.
- Source `.drawio` remains present after rendering.
- Requested pages and formats exist.
- Existing non-target pages remain unchanged.

## Iteration loop

```bash
drawio-cli validate diagram.drawio --strict
drawio-cli render diagram.drawio --format png --output diagram-preview.png
# Inspect diagram-preview.png, edit source, and repeat.
```

On macOS, do not bypass the renderer guard without explicit user approval. Use Linux/Xvfb for automated review when available.

Stop iterating when the diagram communicates its purpose clearly and remaining changes are decorative rather than corrective. Preserve the final reviewed preview or regenerate requested exports from the same final source.
