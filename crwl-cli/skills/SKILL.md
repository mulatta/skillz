---
name: crwl-cli
description: Headless crawler for public web pages. Use to extract clean markdown, structured links, and batch crawl docs/articles.
---

# Use

Use `crwl-cli` for public docs, articles, blogs, product pages, and index pages
that need LLM-readable markdown or structured links. Do **not** use it for
logged-in/private pages, login flows, clicking/typing, uploads, downloads, or
browser automation.

# Workflow

Choose approach before crawling:

| Situation                                                                           | Approach                                     |
| ----------------------------------------------------------------------------------- | -------------------------------------------- |
| Single page (article, docs, blog post)                                              | `crwl-cli fetch URL`                         |
| Multiple pages linked from one page (product listings, search results, index pages) | JSON links pipeline                          |
| Public CMS homepage with notices, menus, sliders, or portal links                   | `--format json --scan-full-page --block-ads` |
| JS-rendered content missing                                                         | Add `--wait-for` or `--scan-full-page`       |
| Ad/tracker noise                                                                    | Add `--block-ads`                            |
| Basic bot blocking on public page                                                   | Add `--stealth --user-agent-mode random`     |

**Never manually copy URLs from markdown output.** For link discovery, crawl
with `--format json` and extract `.links` with `jq`. Markdown links may be
truncated or malformed; `.links` contains structured hrefs.

# Core examples

```bash
# Single public page → filtered markdown
crwl-cli fetch https://docs.python.org/3/library/asyncio.html

# Limit noisy pages to main content
crwl-cli fetch https://docs.python.org/3/ --css "#content"

# Diagnose/render pipelines with structured output
crwl-cli fetch https://example.com --format json

# Raw markdown when filtered markdown misses content
crwl-cli fetch https://example.com --format raw

# JS-rendered content
crwl-cli fetch https://example.com --wait-for ".loaded"

# Quote URLs with query strings so the shell does not split on &
crwl-cli fetch 'https://grad.example.edu/site/index.do?epTicket=LOG&lang=en' \
  --format json --scan-full-page --block-ads

# Fast text-only crawl
crwl-cli fetch https://example.com --text-mode
```

# Multi-step crawling

Use when a page links to multiple detail pages you need to read. Public CMS
homepages often mix notices, menus, sliders, and portal/login links; extract
structured links and follow only public content links.

```bash
# 1. Crawl listing/index page as JSON
crwl-cli fetch https://shop.example.com/products --format json > listing.json

# 2. Extract canonical detail URLs from .links, not .markdown
jq -r '.links.internal[] | select(.href | test("/products/")) | .href' listing.json > urls.txt

# 3. Batch crawl details
crwl-cli fetch --urls-file urls.txt --format json
```

`--format json` output includes:

```json
{
  "url": "...",
  "success": true,
  "status_code": 200,
  "markdown": "...",
  "links": {
    "internal": [{ "href": "...", "text": "...", "title": "..." }],
    "external": [{ "href": "...", "text": "...", "title": "..." }]
  },
  "error": null
}
```

# Options

## Input

- `URL` — single public URL to crawl.
- `--urls-file FILE` — one URL per line. Empty lines and `#` comments ignored.
  Use for batch crawling URLs extracted from JSON links.

## Output

- `--format md|raw|json`
  - `md` default: filtered markdown for LLM reading.
  - `raw`: unfiltered markdown for debugging missing content.
  - `json`: structured output for pipelines and diagnostics.
- `--screenshot` — capture a screenshot for rendering/debugging issues.

## Scope / extraction

- `--css SELECTOR` — limit extraction to a CSS selector.
- `--exclude-tags TAGS` — comma-separated tags to exclude. Default:
  `nav,footer,script,style`.
- `--wait-for SELECTOR` — wait for a CSS selector before extraction.
- `--scan-full-page` — scroll through the full page before extraction; use for
  lazy-loaded public content.

## Headless browser behavior

- `--text-mode` — disable images for faster text-only crawls.
- `--block-ads` — block common ad and tracker requests.
- `--stealth` — enable Crawl4AI/Playwright stealth mode for basic bot blocking.
- `--user-agent-mode default|random` — use default or randomized user agent.
- `--viewport WIDTHxHEIGHT` — set viewport, e.g. `1920x1080`.
- `--ignore-https-errors` — ignore invalid TLS certificates.

## Timing / cache

- `--timeout MS` — page timeout in milliseconds. Default: `30000`.
- `--cache` — enable local cache. Default is off; use only when stale content is
  acceptable.

# Not supported

- Auth profiles or persistent browser profiles.
- Cookie/session import.
- Login flows or private pages, even when linked from an otherwise public page.
- Clicking, typing, uploads, downloads.
- Non-headless browser mode.
- Arbitrary browser config passthrough.

# Troubleshooting

| Problem                 | Try                                                            |
| ----------------------- | -------------------------------------------------------------- |
| Empty markdown          | `--format raw`, `--wait-for SELECTOR`, or `--scan-full-page`   |
| Too much noise          | `--css SELECTOR` or `--exclude-tags TAGS`                      |
| Slow pages              | `--timeout 60000`                                              |
| Images slow things down | `--text-mode`                                                  |
| Ad/tracker noise        | `--block-ads`                                                  |
| Basic bot block         | `--stealth --user-agent-mode random`                           |
| Need links              | `--format json`, then read `.links.internal[]` / `.external[]` |
| Login required          | Stop. `crwl-cli` is for public headless crawling only.         |
