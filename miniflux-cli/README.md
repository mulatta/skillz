# miniflux-cli

Read Miniflux entries from the API, render entry content as Markdown, and fetch
enclosures. The CLI is a source adapter only; workflow processing state belongs
in a separate ledger/tool.

## Configuration

`$XDG_CONFIG_HOME/miniflux-cli/config.json`:

```json
{
  "api_url": "https://rss.example.test",
  "token_command": "rbw get miniflux-api-key"
}
```

Environment overrides:

- `MINIFLUX_URL` / `MINIFLUX_API_URL`
- `MINIFLUX_TOKEN`
- `MINIFLUX_TOKEN_COMMAND`

## Usage

```sh
miniflux-cli list categories
miniflux-cli list feeds --category notification
miniflux-cli list entries --starred --category notification --limit 50 --json
miniflux-cli list entries --search "deadline" --category notification
miniflux-cli show entry 12345             # Markdown with YAML-ish frontmatter
miniflux-cli show entry 12345 --json      # Raw entry JSON
miniflux-cli list enclosures 12345 --json
miniflux-cli fetch enclosure 12345 0 --output-dir ./downloads
```
