# paperfetch-cli

On-demand fetcher for an academic paper's full text + PDF, from a DOI, PMID,
PMCID, or publisher URL, using the host's institutional IP access. Built for
human/agent invocation, not scheduled scraping.

Working: metadata + open-access resolution through OpenAlex, Europe PMC / PMC
OA, and configured Unpaywall, plus byte-level PDF download for arXiv, PMC,
Nature, Cell, Science, and ScienceDirect/Elsevier - self-contained, no
cookie/cache injection.

## Commands

```
paperfetch-cli get <doi|pmid|pmcid|url> [--pdf] [--md] [--html] [--out DIR]
                   [--json] [--unpaywall-email EMAIL]
paperfetch-cli render <url> [--format md|html|text] [--links] [--json]
paperfetch-cli grab <url> --out FILE [--expect MIME] [--from PAGE_URL]
paperfetch-cli setup [--profile-dir DIR] [--chromium PATH]
                     [--unpaywall-email EMAIL]
```

`get` with no artifact flag prints a manifest (probe). `--pdf` tries legal
open-access copies first (Europe PMC / PMC OA when available, then OpenAlex and
configured direct Unpaywall metadata), then the institutional PDF through the
browser. See `skills/SKILL.md` for the agent-facing reference.

## How it works

DOI, PMID, and PMCID inputs are checked against Europe PMC / PMC OA before the
browser path. When those services expose a direct legal PDF, the CLI downloads it
without rendering a publisher page; if that direct URL serves HTML, the browser
fallback opens the cleaner Europe PMC/PMC landing instead of discarding that path.

A headful Chromium under Xvfb (Linux) clears Cloudflare where a headless browser
gets a 403. The PDF is read with an in-page `fetch()` run from a same-origin
sibling page inside a fresh iframe - the iframe's fetch is pristine, bypassing
publisher `window.fetch` bot-detection; navigating to the PDF directly only
opens Chrome's viewer, and an out-of-band client gets a CF 403.

ScienceDirect needs a second path: its `/pdfft` endpoint sits behind an
*interactive* Cloudflare challenge a scripted navigation can never clear (no
`Sec-Fetch-User` gesture). The engine clicks the page's real "View PDF" link (a
gesture, for which CF serves a managed auto-solving challenge) and captures the
resulting popup's own PDF response bytes.

The browser is bundled (stock `chromium` on Linux, prebuilt Chrome for Testing
on macOS, since nixpkgs Chromium is Linux-only); `--executable` / `setup --chromium` override it.

## Unpaywall fallback

Unpaywall requires a contact email. paperfetch-cli never hardcodes one. Set it
with any of:

```bash
paperfetch-cli setup --unpaywall-email you@example.org
PAPERFETCH_UNPAYWALL_EMAIL=you@example.org paperfetch-cli get 10.1234/example --pdf
paperfetch-cli get 10.1234/example --pdf --unpaywall-email you@example.org
```

OpenAlex remains the primary metadata source. Unpaywall fills only missing OA
PDF metadata or replaces a recoverably failed OpenAlex lookup. If no email is
configured, Unpaywall is skipped and the existing browser fallback still runs.

## Per-publisher status

| publisher | Cloudflare | institutional IP | PDF url discovery |
| --- | --- | --- | --- |
| PMC / Europe PMC | none | no | Europe PMC fullTextUrl / PMC OA |
| Nature (Springer) | none | yes | `citation_pdf_url` |
| Cell (Elsevier) | yes, headful passes | yes | `citation_pdf_url` |
| Science (AAAS) | yes, headful passes | yes | adapter (no `citation_pdf_url`) |
| ScienceDirect (Elsevier) | yes; `/pdfft` is a 2nd interactive challenge, cleared by clicking "View PDF" | yes | `pdfDownload.urlMetadata` adapter |

## Auth

Access is **IP-first**: the host is in the publishers' subscriber IP ranges, so
paywalled PDFs download with no login and no maintained session - only the
session the browser builds itself each run, discarded on exit. `--cookies` /
`--profile` are an escape hatch (off-campus / EZproxy), set once via `setup`. On
a host without Xvfb (macOS) the headful browser is visible and Cloudflare does
not auto-clear, so a one-time warmed `--profile` (solve the challenge by hand in
`render`, then reuse) is needed for ScienceDirect.

## Boundaries

This CLI only fetches one paper. Rich literature search (`biorefs-cli`) and
filing the result into Zotero (`zhost-cli`) are a meta-skill's job; this tool
never calls another CLI.
