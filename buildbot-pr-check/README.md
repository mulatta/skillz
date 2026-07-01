# buildbot-pr-check

Inspect Nixbot CI for a GitHub/Gitea pull request: find/watch the build (even
while it is still running), list failed attributes with their flake `attr`, and
fetch failing log tails.

## Usage

```bash
buildbot-pr-check https://github.com/OWNER/REPO/pull/123
buildbot-pr-check https://github.com/OWNER/REPO/pull/123 --watch --interval 30
buildbot-pr-check https://github.com/OWNER/REPO/pull/123 --failures --log-tail 120
```

Add `--json` for a single machine-readable document. Each failure carries a
`log_url` (`…/logs/raw/<attr>`) for `curl | tail/grep` when the bundled tail is
not enough.

## Build discovery

The Nixbot instance is discovered from the forge: Nixbot posts a commit status /
check-run with `target_url`/`details_url` pointing at
`/repos/<forge>/<owner>/<repo>/builds/<number>` as soon as it starts. The tool
reads that, then talks to Nixbot directly. No configuration needed.

## Exit codes

`0` on success, `1` on failure/exception/cancelled.
