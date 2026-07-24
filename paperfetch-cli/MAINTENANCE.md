# paperfetch-cli maintenance review

Date: 2026-07-04
Scope: technical debt, typing, and anti-pattern review of `paperfetch-cli`
after the `enhance-paperfetch-cli` work landed.

## Branch state

- `enhance-paperfetch-cli` carries all paperfetch changes.
- `refactor-repo` is stacked on top and should have no `paperfetch-cli` diff
  relative to `enhance-paperfetch-cli`.
- Live e2e tests are opt-in. Normal package checks do not hit network services.

## Completed hardening

The live Unpaywall e2e test is gated by `PAPERFETCH_LIVE`, matching the other
networked tests. A normal `pytest tests` run no longer calls Unpaywall just
because `PAPERFETCH_UNPAYWALL_EMAIL` exists in the environment.

Suppressed metadata and direct OA download errors now reach the manifest
`warnings` list. Users can see why metadata is sparse or why the browser fallback
started.

Publisher URL helpers now match parsed hosts instead of substrings in the full
URL. ScienceDirect PDF metadata parsing no longer depends on JSON key order.

Browser helper logic has offline unit coverage for challenge detection, expected
content type checks, and origin extraction. Cloudflare/publisher behavior remains
covered by opt-in live e2e tests.

Corrupt `config.json` is reported as a user-facing `CLIError` instead of a raw
`JSONDecodeError` traceback. The PMC OA endpoint still uses the old
`www.ncbi.nlm.nih.gov/pmc` host because the apparent `pmc.ncbi.nlm.nih.gov`
replacement currently returns 404 for `oa.fcgi`.

## Remaining debt

### 1. Typing: `PaperMeta` is mutable and carries an unenforced invariant

`PaperMeta` is still mutable and is updated in place in Europe PMC and arXiv
resolution. The fields `oa_pdf_url`, `oa_pdf_source`, and `oa_landing_url` still
encode an implicit invariant the type system cannot see.

Suggested fix: group those fields into `OaPdf(url, source, landing)` and make
`PaperMeta` frozen. This pairs naturally with merge unification.

### 2. Typing: browser layer is an `Any` hole under strict mypy

The patchright browser/session/page objects are still typed as `Any`. Strict
mypy therefore checks little inside the browser module.

Suggested fix: try patchright's Playwright types first. If stubs prove unstable,
introduce small local Protocols for the methods paperfetch actually uses.

### 3. Anti-pattern: raw `argparse.Namespace` passed through get internals

`cmd_get`, `_emit_get`, `_browser_get`, and `_browser_pdf` still pass raw
`argparse.Namespace` through the call stack. Attribute access remains invisible
to mypy and `_browser_pdf` still needs many parameters.

Suggested fix: convert CLI args into a typed `GetOptions` dataclass at the
command boundary.

### 4. ScienceDirect live coverage is host-dependent

The ScienceDirect live test remains opt-in and Linux-only because its supported
headful automation path needs Xvfb. A current Linux/Xvfb smoke test returned PDF
bytes, while macOS headless did not; neither result makes this best-effort path a
portable guarantee.

Suggested fix: keep a periodic Linux/Xvfb smoke test rather than promoting this
to a required check until PDF byte return is deterministic.

### 5. Papercuts

- Version string `0.1.0` is still maintained in both `__init__.py` and
  `pyproject.toml`; switch to hatch dynamic versioning or `importlib.metadata`.
- `unpaywall_email_from_args` and `browser_config_from_args` still re-read the
  config independently; a typed options object could share one loaded config.
- Watch for a working replacement for the PMC OA `oa.fcgi` host; the current
  `pmc.ncbi.nlm.nih.gov` candidates return 404.
- `resolve.py` still mixes identifier parsing, API clients, publisher scraping,
  and download logic. Split into `identifiers.py`, `sources/`, and
  `publishers.py` when the next source lands.

## Recommended order

1. `PaperMeta`/`OaPdf` redesign.
1. Typed `GetOptions` for `get` internals.
1. Browser typing cleanup.
1. Periodic Linux/Xvfb ScienceDirect validation.
1. Version/config papercuts.
1. Module split when another source is added.
