---
name: paperfetch-cli
description: Fetch one academic paper's full text and PDF on demand from a DOI, PMID, PMCID, or publisher URL, using legal OA sources (Europe PMC / PMC OA) and the host's institutional IP access. Use when an agent needs the PDF or full text of a specific paper (to read, summarize, or file into Zotero). Not a crawler - never loop it over many papers (systematic downloading risks an institution-wide access block). Literature search (biorefs-cli) and filing into Zotero (zhost-cli) belong to a meta-skill; this tool only fetches.
---

# paperfetch-cli

On-demand fetch of one paper's artifacts. Runs a headful Chromium (under Xvfb on
Linux) from the host's institutional IP: paywalled PDFs come back with no login
and no stored credentials - only the session the browser builds itself during
the run. **Not a crawler**; fetch one paper at a time.

## get - the main command

`paperfetch-cli get <doi|pmid|pmcid|url> [--pdf] [--md] [--html] [--out DIR] [--json]`

Resolves the paper and produces the requested artifacts. With **no artifact
flag** it only prints a manifest (a probe - metadata + whether an OA PDF exists).

- `--pdf` - download the PDF to `--out`. Tries legal open-access copies first
  (Europe PMC / PMC OA and OpenAlex, no browser); if paywalled or OA-bot-blocked
  it renders the article page and pulls the institutional PDF through the browser
  (covers Cell, Science, Nature, and ScienceDirect/Elsevier journals). `--pdf-url
  URL` forces an explicit URL and skips discovery. If a PMC direct PDF URL serves
  HTML, the browser fallback keeps the Europe PMC/PMC landing instead of dropping
  back to DOI-only resolution.
- `--md` - render the article page and print full-text markdown to stdout.
- `--html` - save the rendered article HTML to `--out`.
- `--json` - print the manifest as JSON to stdout (else it goes to stderr).

Input may be a DOI (`10.1016/...`), PMID (`PMID:17375194` or bare digits),
PMCID (`PMC1817623` / `PMCID:PMC1817623`), or a publisher/article URL.

```bash
paperfetch-cli get 10.1016/j.cell.2024.04.041 --pdf --out ./papers
paperfetch-cli get PMC1817623 --pdf --out ./papers        # Europe PMC / PMC OA
paperfetch-cli get PMID:17375194 --json                   # PubMed identifier probe
paperfetch-cli get 10.1016/j.bmc.2024.117837 --pdf --out ./papers  # ScienceDirect
paperfetch-cli get 10.1126/science.aea2535 --md          # full text to stdout
paperfetch-cli get 10.1038/s41586-024-08025-4 --json     # probe: metadata + OA
```

## Manifest + exit codes

`get` writes a JSON manifest: `doi`, `pmid`, `pmcid`, `title`, `authors`,
`journal`, `year`, `landing_url`, the resolved `pdf` (`url`, `via` =
`europepmc|pmc_oa|oa|citation_pdf_url|sciencedirect|adapter|explicit`, `path`),
`fulltext` (`chars`), and on failure `candidates.pdf_links`. Exit codes: `0` ok
· `2` usage · `3` an artifact could not be resolved (see `candidates` /
`warnings`) · `4` fetch / Cloudflare blocked.

## Low-level primitives (escape hatch)

- `paperfetch-cli render <url> [--format md|html|text] [--links] [--json]` -
  headful render of a page to markdown/html; `--links` surfaces candidate URLs.
- `paperfetch-cli grab <url> --out FILE [--expect MIME] [--from PAGE_URL]` -
  download a URL's bytes through the browser. `--from` loads a same-origin page
  first (the article page) to clear Cloudflare and let the in-page fetch reach
  the file - **required for publisher PDFs** (e.g. Cell, Science). `--expect`
  fails if the response is not that content type.

```bash
paperfetch-cli grab 'https://www.cell.com/cell/pdf/S0092-8674(26)00643-4.pdf' \
  --from 'https://www.cell.com/cell/fulltext/S0092-8674(26)00643-4' \
  --out paper.pdf --expect application/pdf
```

## Auth

Access is by **institutional IP** - usually no login or cookies. The browser
builds its own ephemeral session each run (publisher + Cloudflare cookies),
discarded on exit. `--cookies FILE` / `--profile DIR` are an escape hatch for
off-campus / EZproxy cases, set once via `paperfetch-cli setup`; never per call.
Never log credentials.

On a host **without Xvfb** (e.g. macOS) the headful browser is visible and
Cloudflare does not auto-clear, so ScienceDirect needs a one-time warmed
`--profile`: `render` the article once and solve the "are you a robot" prompt by
hand, then reuse that `--profile` for unattended `get --pdf` runs until the
cookie expires. On the Linux host (Xvfb) this is unnecessary.
