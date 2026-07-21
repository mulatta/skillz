# Diagram patterns

Choose a pattern before placing cells. Pattern determines reading direction, grouping, edge meaning, and whether official shapes add value.

## Architecture and service dependency

- Prefer `LR` when traffic/data moves from clients toward storage; use `TB` for layered stacks.
- Group by trust boundary, region, cluster, namespace, or responsibility—not by arbitrary color.
- Use rectangles for logical services and cylinders for generic data stores.
- Search official shapes only for products/platform resources whose identity matters.
- Label edges with protocol, event, or data type; omit labels like “calls” when direction already explains them.
- Use graph layout for large dependency networks. Hand-tune only the important overview path.

Recommended visual order:

```text
clients → edge/ingress → application/services → queues/data → external systems
```

## Flowchart and process map

- Prefer `TB` for procedures and approval flows; use `LR` for timelines or pipelines.
- Rounded rectangle: start/end or activity when local convention permits.
- Rectangle: operation.
- Diamond: question/decision.
- Edge label: condition such as `yes`, `no`, `approved`, or `timeout`.
- Keep the normal path visually straight. Route exceptions to one side and merge explicitly.
- Avoid multiple unlabeled outgoing edges from a decision.

Generic styles are enough; shape search usually adds noise.

## Cross-functional flowchart

- Use one flat swimlane per actor/team when only responsibility matters.
- Use a table-like actor × phase grid only when both dimensions are essential.
- Place each step inside its lane/container with relative coordinates.
- Put cross-lane handoff edges on shared layer `1` so lane clipping does not hide them.
- Prefer `LR` inside horizontal lanes and label decision branches.
- Keep lane sizes consistent rather than nesting pools and lanes without a notation requirement.

## BPMN process

- Search local `bpmn` shapes for typed tasks, events, gateways, and data objects; official styles include details that generic approximations omit.
- Sequence flow stays within one pool; message flow crosses pools.
- Center events and gateways on the flow line and keep task direction consistently `LR`.
- Use a pool/lane hierarchy only when roles or participants matter.
- Ask for BPMN fidelity when the diagram could be interpreted operationally; do not invent event or gateway semantics.

## UML class or component diagram

- Keep names and responsibilities concise.
- Class-like boxes can use swimlanes or compartmented labels; do not cram full source declarations into an overview.
- Use open unfilled triangle arrows for generalization and plain/labelled associations for relationships.
- Put cardinality near association endpoints only when required.
- Group components by package/module boundary.
- Prefer `TB` for inheritance trees and `LR` for component dependencies.

For a sequence-like interaction view, place participants in a stable left-to-right order and messages top-to-bottom. Use `shape=umlLifeline;perimeter=lifelinePerimeter;` for lifelines, solid filled arrows for synchronous calls, and dashed open arrows for returns/asynchronous semantics only when that convention is intended. `layout` is not a sequence-diagram engine, so direct XML positioning is usually clearer.

## C4 model

- Separate System Context, Container, and Component views into named pages rather than mixing abstraction levels.
- Keep the standard label hierarchy: name, type/technology, then short responsibility.
- Use one relationship direction and label with action/protocol.
- Distinguish external systems visibly but avoid making color the only distinction.
- Search `c4` shapes when person/system vocabulary matters; otherwise consistent generic boxes are acceptable.
- Optional drill-down uses `UserObject link="data:page/id,PAGE_ID"`; verify every target page ID.

This CLI has no C4 generator, so build and replace pages deliberately. Preserve all existing pages with guarded `replace-page`.

## SysML and engineering notation

- Search official `sysml` shapes and preserve stereotype/connector semantics.
- Ask whether the user needs block definition, internal block, requirement, or parametric notation.
- Keep multiplicity, ports, item flows, satisfy/verify/trace relations, and requirement IDs explicit when provided.
- Never infer safety- or compliance-critical engineering meaning from visual similarity.

## ERD

- Use one box per entity with name and only relevant attributes.
- Highlight primary and foreign keys textually; do not rely on color alone.
- Label relationships and cardinality consistently.
- Arrange high-connectivity entities near the center while avoiding edge crossings.
- Split operational and analytical domains into separate pages when one ERD becomes dense.
- Use generic entity boxes unless the user explicitly requires a particular notation.

Graph layout helps with topology, but inspect every cardinality label after rendering.

## Cloud, network, and Kubernetes

- Search official shapes with vendor and resource terms, for example `aws lambda`, `azure function`, `gcp compute`, `kubernetes pod`, or `cisco router`.
- Do not mix icon generations or vendors without explanation.
- Use containers for account/project, region, VPC/VNet, cluster, namespace, subnet, or zone only when those boundaries matter.
- Keep logical application flow separate from physical network topology when combining them would overload one diagram.
- Use line style or labels to distinguish request traffic, asynchronous events, replication, and management paths.
- Add a legend only when styles are not self-evident.

Never guess `mxgraph.*` style identifiers. Copy exact single-cell styles from local search.

## ML or data-processing model

- Prefer `TB` for tensor/data flow and `LR` for pipeline stages when labels remain readable.
- Group encoder/decoder, training/inference, or preprocessing/model/postprocessing boundaries.
- Put tensor dimensions on a second line with `&#xa;`, using a consistent convention such as `(B, C, H, W)` or `(B, T, D)`.
- Use distinct restrained colors for layer roles and dashed/curved edges only for skip or auxiliary connections.
- Keep paper figures concise; implementation details belong in annotations or separate pages.

## P&ID and electrical

- Search official local shapes before authoring symbols.
- Preserve conventional connectivity and symbol semantics; decorative approximations can be misleading.
- Label equipment, valves, instruments, nets, and signals with user-provided identifiers.
- Prefer orthogonal routing and visible junctions.
- Distinguish process, control, and electrical connections consistently.
- Ask for notation or standard details when correctness depends on them; do not infer safety-critical meaning.

Use `--fuzzy` only after exact multi-term search fails, then inspect every result before insertion.

## Choosing one page versus several

Create separate pages when the audience or level of detail changes:

- overview versus implementation
- logical versus deployment
- request path versus failure/recovery path
- application architecture versus network topology
- current state versus target state

Keep page names stable and descriptive. Existing multi-page edits must use a page selector and guarded `replace-page` so unrelated pages remain untouched.
