# linkwarden-cli

Agent-oriented CLI for Linkwarden bookmark management.

## Setup

`setup` writes config and confirms `token_command` returns a non-empty value. It
does not call the Linkwarden API.

```bash
linkwarden-cli setup \
  --base-url https://linkwarden.example.com \
  --token-command "rbw get linkwarden-token"
```

Configuration is stored in:

```text
${XDG_CONFIG_HOME:-~/.config}/linkwarden-cli/config.json
```

Environment overrides:

```text
LINKWARDEN_BASE_URL
LINKWARDEN_URL
LINKWARDEN_TOKEN
LINKWARDEN_TOKEN_COMMAND
```

## Usage

```bash
linkwarden-cli link search 'postgres tag:nix after:2026-01-01'
linkwarden-cli link get 123
linkwarden-cli link create https://example.com --name Example --tag research --collection Inbox
linkwarden-cli link update 123 --name "New title"
linkwarden-cli link delete 123 --yes
linkwarden-cli link archive 123

linkwarden-cli collection list
linkwarden-cli collection create Inbox
linkwarden-cli tag list --search nix
linkwarden-cli highlight list 123
linkwarden-cli rss list
linkwarden-cli token list

linkwarden-cli api GET /api/v1/users/me
```

Add `-j`/`--json` before the command for raw JSON output.
