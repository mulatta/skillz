# paperfetch-cli

On-demand fetcher for an academic paper's full text + PDF, from a DOI, arXiv ID,
PMID, PMCID, or publisher URL, using the host's institutional IP access. Built
for human/agent invocation, not scheduled scraping.

Working: metadata + open-access resolution through OpenAlex, native arXiv,
Europe PMC / PMC OA, and configured Unpaywall, plus byte-level PDF download for
arXiv, PMC, Nature, Cell, and Science. ScienceDirect/Elsevier remains
best-effort because its PDF path can require interactive browser state that does
not always return bytes to the CLI.

## Commands

```
paperfetch-cli get <doi|arxiv|pmid|pmcid|url> [--pdf] [--md] [--html] [--out DIR]
                   [--json] [--unpaywall-email EMAIL]
paperfetch-cli render <url> [--format md|html|text] [--links] [--json]
paperfetch-cli grab <url> --out FILE [--expect MIME] [--from PAGE_URL]
paperfetch-cli setup [--profile-dir DIR] [--chromium PATH]
                     [--unpaywall-email EMAIL]
```

`get` with no artifact flag prints a manifest (probe). `--pdf` tries legal
open-access copies first (native arXiv, Europe PMC / PMC OA when available, then
OpenAlex and configured direct Unpaywall metadata), then the institutional PDF
through the browser. See `skills/SKILL.md` for the agent-facing reference.

Examples:

```bash
paperfetch-cli get arXiv:2401.12345 --pdf --out ./papers
paperfetch-cli get hep-th/9901001 --json
paperfetch-cli get PMID:12345678 --json
paperfetch-cli get PMCID:PMC1234567 --pdf --out ./papers
paperfetch-cli get 'https://www.biorxiv.org/content/10.1101/2024.01.02.123456v2.full' --pdf
```

## How it works

arXiv IDs (`2401.12345`, `arXiv:2401.12345`, old-style IDs when recognized)
resolve to `https://arxiv.org/pdf/<id>.pdf` directly, with a single-record arXiv
metadata lookup when possible. DOI, PMID, and PMCID inputs are checked against
Europe PMC / PMC OA before the browser path. Common bioRxiv/medRxiv article URLs
are normalized to their DOI. When OA services expose a direct legal PDF, the CLI
downloads it without rendering a publisher page; if that direct URL serves HTML,
the browser fallback opens the cleaner Europe PMC/PMC landing instead of
discarding that path.

A headful Chromium under Xvfb (Linux) clears Cloudflare where a headless browser
gets a 403. The PDF is read with an in-page `fetch()` run from a same-origin
sibling page inside a fresh iframe - the iframe's fetch is pristine, bypassing
publisher `window.fetch` bot-detection; navigating to the PDF directly only
opens Chrome's viewer, and an out-of-band client gets a CF 403.

ScienceDirect is intentionally treated as best-effort. Even on the Linux/Xvfb
host where headful Chromium clears the article challenge, a browser-authenticated
article session can load the article and Chrome PDF viewer while `/pdfft` still
returns HTML to scripted fetches instead of `%PDF-` bytes. On failure the CLI
reports sanitized page diagnostics and candidate PDF links so a caller can hand
off to a human browser session.

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
| ScienceDirect (Elsevier) | yes; PDF path may need interactive handoff | yes | `pdfDownload.urlMetadata` adapter, best-effort |

## Auth

Access is **IP-first**: the host is in the publishers' subscriber IP ranges, so
paywalled PDFs usually download with no login and no maintained session - only
the session the browser builds itself each run, discarded on exit. `--cookies` /
`--profile` are an escape hatch (off-campus / EZproxy), set once via `setup`.
Use `render --profile DIR` only when manually operating the browser on that host
is acceptable; otherwise treat ScienceDirect failures as a manual handoff case.

## Live tests

Normal package checks do not hit the network. Opt into source-by-source live
coverage with environment variables:

```bash
PAPERFETCH_LIVE=1 pytest tests/test_live_e2e.py
PAPERFETCH_LIVE_BROWSER=1 pytest tests/test_live_e2e.py
PAPERFETCH_LIVE_UNPAYWALL_EMAIL=you@example.org PAPERFETCH_LIVE=1 pytest tests/test_live_e2e.py
```

ScienceDirect is gated separately because its PDF byte-return path is
best-effort even on Linux/Xvfb after the article challenge clears:

```bash
PAPERFETCH_LIVE_BROWSER=1 PAPERFETCH_LIVE_SCIENCEDIRECT=1 pytest tests/test_live_e2e.py
```

## Boundaries

This CLI only fetches one paper. Rich literature search (`biorefs-cli`) and
filing the result into Zotero (`zhost-cli`) are a meta-skill's job; this tool
never calls another CLI.
