# zhost-cli

Agent-oriented CLI for a self-hosted Zotero sync server (**zhost**). It speaks the
Zotero Web API v3 sync subset so an agent can file papers into a private Zotero
library — collections, items, PDF attachments, highlights, notes, and tags —
without touching zotero.org.

It is a **client**. The server lives in a separate repo:

- Server source / protocol spec: `~/git/zhost` (authoritative: `~/git/zhost/server/SPEC.md`)

This CLI deliberately does not vendor or restate the protocol; the spec there is
the single source of truth. For local development, point `--base-url` at a running
zhost instance (e.g. `http://127.0.0.1:8189`).

## Install / run

Built with the rest of the `skillz` flake:

```bash
nix run .#zhost-cli -- find aptamer
```

## Configure

Credentials come from `$XDG_CONFIG_HOME/zhost-cli/config.json` or `ZHOST_*`
environment variables. The API key is provisioned out of band (never minted by
this CLI). Set up once:

```bash
zhost-cli setup \
  --base-url https://zotero.example.com \
  --api-key-command "rbw get zhost-key" \
  --user-id 1
```

Environment overrides: `ZHOST_BASE_URL`, `ZHOST_API_KEY`, `ZHOST_API_KEY_COMMAND`,
`ZHOST_USER_ID`, `ZHOST_TIMEOUT`.

## Commands

Noun > verb. `item add` is composite (create + attach PDF + file in a collection

- tag, in one call); `item add` creates while `item edit` modifies — using add to
  update makes a duplicate.

```text
zhost-cli [--config PATH] [-j/--json]
├── setup --base-url --api-key-command [--user-id]
├── item
│     add    [--type --title --author.. --date --doi --journal --url]
│            [--pdf PATH] [--collection NAME] [--tag T..] [--file JSON]
│     list   [--all --trash --collection NAME --type --tag]  # paged bulk dump
│     find   QUERY [--type --tag --limit]   # full-text search (title + body) -> items
│     get    KEY                            # item with its children
│     edit   KEY [--set field=v | --file]
│     move   KEY --collection NAME[,..]     # re-file (replaces membership)
│     remove KEY --yes                      # delete any item
├── collection
│     list                                  # tree
│     create NAME [--parent KEY]
│     rename KEY NAME
│     move   KEY (--parent KEY | --top)
│     items  KEY [--type --tag --limit]
│     remove KEY --yes                      # folder only; its items stay
├── library
│     export OUTDIR [--collection NAME] [--no-files]  # whole-library archive
│     import INDIR  [--no-files]            # restore (keys preserved)
├── highlight add ITEM --pdf PATH --text T [--color --comment --page --tag] | list ITEM
├── note      add ITEM (--text HTML | --file) [--tag] | list ITEM
├── tag       add KEY NAME.. | remove KEY NAME.. | list [KEY]
├── pdf       attach ITEM --pdf | fetch ITEM --output | replace ITEM --pdf
└── api METHOD PATH [--query k=v] [--header k=v] [--body JSON|--file]
```

`highlight`/`note`/`pdf` take an **item** key and resolve its PDF attachment
internally — you never handle attachment keys. `item find` resolves full-text
hits (which land on attachments) up to their parent items. Every `list`/`find`/
`get` honours `-j` for JSON.

See `skills/SKILL.md` for the agent workflow and the rules that keep writes
correct (server-minted keys, idempotent collections, version preconditions,
merge semantics, deterministic highlight geometry).

## Notes

- `highlight` computes PDF rects with pymupdf (exact `search_for`, falling back
  to a word-stream match that survives hyphenated line breaks); `--text` must
  appear in the PDF. No LLM tokens are used for geometry.
- Object keys are 8 chars from a 32-symbol alphabet (no 0/1/O/L); the CLI lets
  the server assign them and validates any user-supplied key before sending.
