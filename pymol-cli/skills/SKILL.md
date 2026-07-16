---
name: pymol-cli
description: Control PyMOL molecular visualization sessions through XML-RPC and generate repeatable PML views. Use whenever the user asks to open, show, color, zoom, label, screenshot, ray render, manipulate, or send commands to PyMOL; inspect or highlight ligands, binding pockets, chains, residues, domains, interfaces, or scenes in an already loaded PDB/mmCIF; or restart PyMOL with remote control. Prefer this skill over ad-hoc xmlrpc.client snippets.
---

# pymol-cli

Use `pymol-cli` for PyMOL session control and repeatable structure visualization. The CLI assumes local PyMOL XML-RPC (`-R`) on `localhost:9123` unless told otherwise.

## Core rules

- Use `pymol-cli status` before sending commands when session state is uncertain.
- If PyMOL was not started with `-R`, restart it with `pymol-cli launch`. Launch uses `pueue` by default because PyMOL is long-running.
- Keep PML commands explicit and reproducible. Save generated scripts when view state matters.
- Use structural data sources (RCSB/mmCIF, UniProt residue annotations) for biological claims; PyMOL selections are visualization/geometry evidence.
- Do not use hidden scraping or non-local remote hosts unless user explicitly provides host/port.
- Prefer `pymol-cli ligand-pocket` for common ligand-neighborhood views instead of hand-writing long XML-RPC Python snippets.

## Commands

```bash
# Start PyMOL with XML-RPC via nix and pueue defaults
pymol-cli launch --script show.pml

# Check connection
pymol-cli status
pymol-cli status -j

# Load a structure with basic styling
pymol-cli load structure.cif --object protein
pymol-cli load structure.cif --object protein --style sticks --output load_view.pml
pymol-cli load https://example.org/model.cif --object protein --allow-url

# Send commands
pymol-cli do 'bg_color white' 'zoom all, 5'
pymol-cli script view.pml
pymol-cli do --stdin < view.pml

# Render current view
pymol-cli render view.png --width 1600 --height 1200
pymol-cli render ray.png --ray

# Count atoms in a selection
pymol-cli count 'resn LIG'
pymol-cli count '(chain A and polymer)'

# Generate PML only (stdout)
pymol-cli ligand-pocket --object protein --ligand LIG --chains A,B --grid

# Generate and send ligand pocket view
pymol-cli ligand-pocket \
  --object protein \
  --ligand LIG \
  --chains A,B \
  --distance 4 \
  --color A:cyan --color B:slate \
  --mark A:123,145 --mark B:98 \
  --grid \
  --scene ligand_pockets \
  --output ligand_pockets.pml \
  --send
```

Options common to XML-RPC commands:

- `--host localhost`
- `--port 9123`
- `--timeout 5`
- `-j/--json`

## Workflow: restart PyMOL so commands can be sent

1. Kill stale non-remote PyMOL if needed:

   ```bash
   pueue kill <task-id>
   ```

1. Start remote PyMOL:

   ```bash
   id=$(pymol-cli launch --script show.pml)
   pueue log --lines 80 "$id"
   ```

1. Confirm XML-RPC:

   ```bash
   pymol-cli status
   ```

## Workflow: load structure and basic style

Write a small PML file when view should be reproducible:

```pml
load structures/4hhb_assembly1.cif, hb
hide everything
show cartoon, hb and polymer
color red, hb and chain A+C
color marine, hb and chain B+D
show sticks, hb and resn HEM
color orange, hb and resn HEM
bg_color white
orient hb
zoom hb, 8
```

For common load-and-style cases, use `load` instead. Local files are the default; URL loads require `--allow-url` so remote fetches are explicit.

```bash
pymol-cli load structures/4hhb_assembly1.cif --object hb --style cartoon --color gray70
```

Then run saved scripts with:

```bash
pymol-cli script view.pml
```

## Workflow: ligand pocket view

Use `ligand-pocket` when user asks to show ligand-binding residues, binding site, pocket, or residues near ligand. Before `--send`, it checks ligand atoms per requested chain and every `--mark` residue. Partial ligand occupancy warns and skips missing chains; complete absence or missing marked residues fails before restyling.

- `--object`: loaded PyMOL object, e.g. `hb`.
- `--ligand`: residue name, e.g. `HEM`, `ATP`, `NAD`.
- `--chains`: comma-separated chain ids.
- `--distance`: residue shell around ligand, default `4.0` Å.
- `--mark CHAIN:RESI[,RESI]`: highlight known catalytic/binding residues in magenta and label them.
- `--color CHAIN:COLOR`: color chain cartoon.
- `--grid`: show each chain/object in separate grid panel.
- `--scene NAME`: store PyMOL scene after view is built.
- `--output FILE`: save generated PML for replay/review.
- `--strict-chains`: fail instead of skipping when ligand is absent from any requested chain.
- `--no-validate`: skip ligand and marked-residue preflight for structures whose unusual naming makes normal PyMOL selections inaccurate.
- `--send`: execute immediately; without it, print PML or output path.

For hemoglobin heme pockets:

```bash
pymol-cli ligand-pocket \
  --object hb --ligand HEM --chains A,B,C,D --distance 4 \
  --color A:red --color C:red --color B:marine --color D:marine \
  --mark A:58,87 --mark C:58,87 --mark B:63,92 --mark D:63,92 \
  --grid --scene heme_pockets_grid --send
```

## Screenshots and rendering

Use `render` for common PNG output:

```bash
pymol-cli render view.png --width 1600 --height 1200 --dpi 200
pymol-cli render ray.png --width 1600 --height 1200 --dpi 200 --ray
```

Use `pueue` for expensive ray renders if invoking PyMOL non-interactively. For already-open remote sessions, `pymol-cli render` returns after PyMOL accepts the command; long rendering still happens inside PyMOL.

## Troubleshooting

- `cannot connect`: PyMOL is not running with `-R`, port differs, or previous launch still fetching/building. Check `pueue log`.
- `has_do: false`: XML-RPC server is up but not PyMOL command API; restart PyMOL with `-R`.
- Selection gives zero atoms: verify object name, chain ids, ligand residue name, and whether mmCIF loaded biological assembly or asymmetric unit.
- Chain-local ligand selection matters after copying per-chain objects. `ligand-pocket` uses `(site_X and resn LIG)` to avoid matching ligand in another chain.
