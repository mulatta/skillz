# Third-party notices

Original repository code is licensed under the repository's MIT `LICENSE`. The following components and adapted material retain their own licenses and terms.

## jgraph/drawio-mcp

- Source: https://github.com/jgraph/drawio-mcp
- Revision inspected: c3fcfa5
- License: Apache-2.0
- Sources inspected: `shared/xml-reference.md`, `shared/style-reference.md`, `shared/shape-search.js`, and `plugins/codex/drawio/skills/drawio/SKILL.md`.
- Local use: `xml-authoring.md`, `style-reference.md`, `shape-search.md`, and the file-first workflow, rewritten for offline local files.
- Deliberate changes: browser URLs, Mermaid conversion, MCP/ELK/libavoid calls, remote image rewriting, source deletion, and direct Desktop CLI discovery were removed.

## Agents365-ai/drawio-skill

- Source: https://github.com/Agents365-ai/drawio-skill
- Revision inspected: 6f33563
- License: MIT
- Sources inspected: `SKILL.md`, `references/autolayout.md`, `references/diagram-types.md`, validator, Graphviz layout, and PNG repair scripts.
- Local use: validation/layout/PNG behavior plus `layout.md`, `diagram-patterns.md`, `visual-review.md`, and troubleshooting workflow.
- Deliberate changes: importers, presets, live infrastructure, browser fallback, CDN icons, Mermaid, C4/sequence generators, and automatic Desktop invocation were not included.

## jgraph/drawio / drawio-desktop

- Source: packaged by nixpkgs `pkgs.drawio`
- License: Apache-2.0 plus draw.io asset/stencil terms
- Use: Desktop renderer and build-time shape index source.

## defusedxml

- Source: packaged by nixpkgs `python3Packages.defusedxml`
- License: Python-2.0
- Use: safe XML parsing for draw.io files and replacement pages.
