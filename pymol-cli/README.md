# pymol-cli

Agent-oriented helper for PyMOL XML-RPC sessions and repeatable structure views.

PyMOL must be started with remote control enabled (`-R`):

```bash
pymol-cli launch --script show.pml
pymol-cli status
pymol-cli load structure.cif --object protein
pymol-cli do 'bg_color white'
pymol-cli render view.png --ray
pymol-cli script edits.pml
```

Generate and optionally send a ligand-pocket view:

```bash
pymol-cli ligand-pocket \
  --object protein \
  --ligand LIG \
  --chains A,B \
  --color A:cyan --color B:slate \
  --mark A:123,145 --mark B:98 \
  --grid \
  --scene ligand_pockets \
  --output ligand_pockets.pml \
  --send
```

Default XML-RPC endpoint is `http://localhost:9123/RPC2`.
