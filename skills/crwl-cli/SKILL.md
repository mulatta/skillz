---
name: crwl-cli
description: Crawl web pages and extract markdown. Handles auth via browser profiles.
---

# Workflow Selection

Choose approach **before** crawling:

| Situation | Approach |
|-----------|----------|
| Single page (article, docs, blog post) | `crwl-cli fetch URL` |
| Multiple pages linked from one page (product listings, search results, index pages) | **JSON links pipeline** (see Multi-step Crawling) |

**NEVER manually copy URLs from markdown output.** Use `--format json` and extract `.links` with `jq` instead. Markdown text may contain malformed or incomplete URLs, while `.links` provides structured, reliable hrefs.

# Basic Usage

```bash
# Single URL — markdown output (default)
crwl-cli fetch https://docs.python.org/3/library/asyncio.html

# CSS selector to limit scope
crwl-cli fetch https://docs.python.org/3/ --css "#content"

# JSON output (for pipelines)
crwl-cli fetch https://example.com --format json

# Raw markdown (no content filtering)
crwl-cli fetch https://example.com --format raw

# Fast mode — disable images
crwl-cli fetch https://example.com --text-mode

# Wait for dynamic content
crwl-cli fetch https://example.com --wait-for ".loaded"

# Batch crawl from file
crwl-cli fetch --urls-file urls.txt --format json
```

# Multi-step Crawling

When to use: the target page **links to multiple detail pages** you need data from.
Detect this when the page is a product listing, search results, category index, or configurator.

## Steps

```bash
# 1. Crawl listing page → JSON (always use --format json for listings)
crwl-cli fetch https://shop.example.com/products --format json > listing.json

# 2. Extract detail page URLs via .links (NOT from .markdown)
jq -r '.links.internal[] | select(.href | test("/products/")) | .href' listing.json > urls.txt

# 3. Batch crawl all detail pages
crwl-cli fetch --urls-file urls.txt --format json
```

## `links` structure (`--format json` only)

```json
{
  "internal": [{"href": "...", "text": "...", "title": "..."}],
  "external": [{"href": "...", "text": "...", "title": "..."}]
}
```

## Agent decision logic

1. Crawl the target URL with `--format json`
2. Check: does `.links.internal` contain multiple URLs matching a detail page pattern?
   - Yes → filter with `jq`, write to file, batch crawl with `--urls-file`
   - No → use `.markdown` directly
3. Extract needed information from each result's markdown

## Anti-patterns

- **Reading `.markdown` to find URLs** — unreliable, manual, and misses links hidden in JS-rendered elements. Always use `.links`.
- **Manually constructing detail page URLs** — fragile if URL scheme changes. Let `.links` provide the canonical hrefs.
- **Crawling detail pages one by one** — use `--urls-file` for batch crawling instead of sequential fetch calls.

# Authentication Workflow

When crawl output contains login prompts ("sign in", "log in", 403/401), follow these steps:

1. **Create a profile** — opens Chromium for manual login (**requires GUI display; not available in SSH/headless environments**):
   ```bash
   crwl-cli profile create github
   ```
   Log in to the site in the browser window, then press `q` in terminal to save.

2. **Verify the profile works:**
   ```bash
   crwl-cli profile check github https://github.com/settings/profile
   ```
   Check that the preview shows authenticated content.

3. **Crawl with the profile:**
   ```bash
   crwl-cli fetch https://github.com/settings/profile --profile github
   ```

## Auth Detection Heuristics

Re-crawl with a profile when the result contains:
- Keywords: "sign in", "log in", "password", "authentication required"
- HTTP status: 401, 403
- Markdown is unexpectedly short (<100 chars) for a known content-rich page

# Profile Management

```bash
crwl-cli profile list                              # List all profiles
crwl-cli profile create <name>                     # Create (opens browser)
crwl-cli profile check <name> <url>                # Test profile session
crwl-cli profile delete <name>                     # Delete profile
```

Profiles stored at: `~/.local/share/crwl-cli/profiles/<name>/`

> `profile create` opens a Chromium window and requires a GUI display.

# Cache Management

Cache is **off by default**. Enable with `--cache`.

```bash
crwl-cli fetch https://example.com --cache         # Store result
crwl-cli cache list                                # List cached entries
crwl-cli cache clear                               # Clear all
crwl-cli cache clear --older-than 7                # Clear entries >7 days old
```

Cache stored at: `~/.local/share/crwl-cli/cache/`

# Output Formats

| Format | Flag | Content | Use Case |
|--------|------|---------|----------|
| md | `--format md` (default) | Filtered markdown (PruningContentFilter) | LLM consumption |
| raw | `--format raw` | Full markdown, no filtering | Debugging, complete extraction |
| json | `--format json` | `{url, success, status_code, markdown, links, error}` | Pipelines, batch processing |

# Troubleshooting

| Problem | Solution |
|---------|----------|
| Empty markdown | Add `--wait-for <selector>` for JS-rendered content |
| Timeout | Increase `--timeout 60000` |
| Too much noise | Use `--css <selector>` to scope extraction |
| Images slow things down | Use `--text-mode` |
| Auth wall | Create a profile: `crwl-cli profile create <name>` |
| Stale session | Re-check: `crwl-cli profile check <name> <url>` |
