# Style reference

A draw.io style is a semicolon-separated list of bare class/shape tokens and `key=value` pairs. Keys and values are case-sensitive, booleans are `0`/`1`, and spaces around `=` or `;` are invalid. Keep a trailing semicolon. Unknown keys may be silently ignored, so validation and visual review matter. Start with the smallest style that conveys meaning; excessive shadows, gradients, fonts, and colors reduce consistency.

## Generic vertices

Rectangle or service:

```text
rounded=0;whiteSpace=wrap;html=1;
```

Rounded process/service:

```text
rounded=1;whiteSpace=wrap;html=1;arcSize=12;
```

Decision:

```text
rhombus;whiteSpace=wrap;html=1;
```

Ellipse or actor endpoint:

```text
ellipse;whiteSpace=wrap;html=1;aspect=fixed;
```

Database/data store:

```text
shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;
```

Input/output parallelogram:

```text
shape=parallelogram;perimeter=parallelogramPerimeter;whiteSpace=wrap;html=1;
```

Document:

```text
shape=document;whiteSpace=wrap;html=1;boundedLbl=1;
```

Plain text annotation:

```text
text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;
```

Use generic shapes for flowcharts, ERD entities, UML boxes, labels, and boundaries. Do not search the large shape index when a rectangle, diamond, ellipse, cylinder, or text label is sufficient.

## Containers

Titled horizontal swimlane/container:

```text
swimlane;horizontal=1;startSize=30;rounded=1;html=1;whiteSpace=wrap;
```

Untitled visual boundary:

```text
rounded=1;whiteSpace=wrap;html=1;fillColor=none;dashed=1;container=1;
```

Prefer a titled container when group membership carries meaning such as region, trust boundary, namespace, team, or lifecycle stage. Keep children inside with clear padding. Add `pointerEvents=0;` to non-connectable custom boundaries so they do not capture child links. Do not use decorative groups that add no semantic information.

## Edges

Default orthogonal relationship:

```text
edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;endFill=1;
```

Undirected association:

```text
edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;html=1;startArrow=none;endArrow=none;
```

Asynchronous or optional flow:

```text
edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;html=1;dashed=1;endArrow=open;endFill=0;
```

Inheritance/generalization:

```text
edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=0;
```

Entity relationship:

```text
edgeStyle=entityRelationEdgeStyle;html=1;
```

Omit `edgeStyle` for a straight UML/sequence connector. Use `curved=1;` for mind-map-like relations, not architecture flow. `jumpStyle=arc;` can clarify unavoidable crossings but does not replace better layout.

Use edge labels for protocol, cardinality, event, or condition. Keep arrow semantics consistent across one diagram. Avoid diagonal straight lines through nodes; prefer auto-routed orthogonal edges unless a diagram type requires another convention. Non-rectangular generic shapes should include their matching perimeter when the bare style class does not already supply it.

## Color and readability

Default to restrained, light fills with dark text and strokes:

```text
fillColor=#dae8fc;strokeColor=#6c8ebf;fontColor=#1f2937;
fillColor=#d5e8d4;strokeColor=#82b366;fontColor=#1f2937;
fillColor=#fff2cc;strokeColor=#d6b656;fontColor=#1f2937;
fillColor=#f8cecc;strokeColor=#b85450;fontColor=#1f2937;
```

- Use color to encode one stable dimension, not decoration.
- Combine color with labels or shape differences; color alone is inaccessible.
- Keep text/background contrast high.
- Use one font family and a small size hierarchy.
- Avoid hard-coded white text unless the fill is reliably dark.
- Check final PNG/SVG appearance rather than assuming editor colors remain readable.
- For theme-aware files, set `adaptiveColors="auto"` on `mxGraphModel`; use `light-dark(light,dark)` only when automatic adaptation is inadequate.

## Text and HTML labels

Use `whiteSpace=wrap;html=1;` for ordinary wrapped labels. Escape partial HTML formatting inside XML attributes:

```text
value="&lt;b&gt;Title&lt;/b&gt;&lt;br&gt;Description"
```

Use `&#xa;` for a line break that works without HTML. Never put literal `\n` in a label. Whole-label style uses the `fontStyle` bitmask: `1` bold, `2` italic, `4` underline, and sums combine them. Common alignment keys are `align`, `verticalAlign`, `labelPosition`, and `verticalLabelPosition`.

## Official indexed shapes

For AWS, Azure, GCP, Kubernetes, Cisco/network, P&ID, electrical, and branded symbols, run `drawio-cli search-shapes QUERY --json` and copy the returned `style` exactly for a single-cell `vertex` or `edge` result.

Do not invent styles such as `shape=mxgraph.vendor.thing`. Shape names and library versions change. Exact local search ties the style to the packaged draw.io source.

A result with `kind: template` can contain multiple cells in `templateXml`. It is not equivalent to its empty or partial `style`. This CLI does not safely instantiate composite templates automatically; use a single-cell result or perform a deliberate XML insertion with unique IDs and corrected parents, followed by strict validation and visual review.

## Images and links

- Never use `image=https://...` or an icon CDN.
- Prefer draw.io's local built-in stencil styles from shape search.
- Do not assume an arbitrary filesystem image path will remain portable inside `.drawio`.
- If a user explicitly requests an embedded image, use a data URI only after checking file size and redistribution rights.
- Keep ordinary metadata links separate from image resources; offline rendering must not require network access.
