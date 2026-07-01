---
name: buildbot-pr-check
description: Inspect Nixbot CI for a PR. Use to find/watch the build for a PR, list failed attributes with their attrs, and fetch failing log tails.
---

```bash
buildbot-pr-check <pr-url>                                # build + per-attribute status table
buildbot-pr-check <pr-url> --watch --interval 60          # poll until complete; exit 0=success 1=failure
buildbot-pr-check <pr-url> --failures --log-tail 80       # failed attributes: attr, error, log tail + log_url
```

`<pr-url>` is a GitHub `…/pull/N` or Gitea `…/pulls/N` URL (omit to auto-detect
the current branch's PR via `gh`). The Nixbot instance is discovered from the
forge's commit statuses/check-runs; no config. Add `--json` for structured
output:

```bash
buildbot-pr-check <pr-url> --failures --json | jq -r '.failures[] | "\(.attr)\t\(.status)\t\(.log_url // "-")"'
```

Need more than the tail? `log_url` is a plain Nixbot `…/logs/raw/<attr>`
endpoint — `curl -s "$log_url" | tail -n 500` / `| grep error:`.

Nixbot statuses are upper-cased (`SUCCEEDED FAILED BUILDING SKIPPED_LOCAL`).
