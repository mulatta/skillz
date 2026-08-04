"""CLI for inspecting Nixbot CI for a pull request.

Resolves a PR to its Nixbot build and attributes::

    --watch          poll until complete
    --failures       only failed attributes, with log tail + raw log_url
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any, cast

from . import gitea_api, github_api
from .exceptions import CheckError, InvalidPRURLError
from .git import get_current_branch_pr_url
from .nixbot_api import NixbotAttribute, NixbotBuild, NixbotClient, NixbotEvalBuild
from .reporting import (
    ReportAttribute,
    ReportEvalBuild,
    print_eval_build,
    print_failures,
)
from .url_parser import PRInfo, get_pr_info, parse_nixbot_url

# --------------------------------------------------------------------------- #
# PR → nixbot build discovery
# --------------------------------------------------------------------------- #


def _resolve_pr(arg: str | None) -> PRInfo:
    if arg and arg.isdigit():
        # bare PR number → use current repo via gh
        url = get_current_branch_pr_url()
        if not url:
            msg = "Bare PR number given but could not detect repo via `gh`"
            raise CheckError(msg)
        info = get_pr_info(url)
        return PRInfo(info.platform, info.host, info.owner, info.repo, arg)
    if arg:
        return get_pr_info(arg)
    url = get_current_branch_pr_url()
    if not url:
        msg = (
            "No PR URL given and could not auto-detect one for the current branch. "
            "Pass a GitHub/Gitea PR URL."
        )
        raise CheckError(msg)
    return get_pr_info(url)


def _head_sha(pr: PRInfo) -> str:
    if pr.platform == "github":
        return github_api.get_pr_head_sha(pr.owner, pr.repo, pr.pr_num)
    return gitea_api.get_pr_head_sha(pr.host, pr.owner, pr.repo, pr.pr_num)


def _nixbot_urls(pr: PRInfo, head_sha: str) -> list[str]:
    if pr.platform == "github":
        return github_api.get_nixbot_urls_from_github(pr.owner, pr.repo, head_sha)
    return gitea_api.get_nixbot_urls_from_gitea(pr.host, pr.owner, pr.repo, head_sha)


def _discover_eval_build(pr: PRInfo, head_sha: str) -> tuple[NixbotClient, NixbotBuild]:
    """Find the top-level Nixbot build via the forge's status target URLs."""
    urls = _nixbot_urls(pr, head_sha)

    for url in urls:
        try:
            ref = parse_nixbot_url(url)
        except InvalidPRURLError:
            continue
        client = NixbotClient(ref.base_url, ref.forge, ref.owner, ref.repo)
        return client, client.get_build_by_number(ref.build_num)

    msg = (
        f"No nixbot status found on {pr.platform} for "
        f"{pr.owner}/{pr.repo}#{pr.pr_num} ({head_sha[:10]}). "
        f"Either the build has not been scheduled yet or the forge API is unreachable."
    )
    raise CheckError(msg)


# --------------------------------------------------------------------------- #
# `pr` (incl. --watch / --failures)
# --------------------------------------------------------------------------- #


def _emit_json(obj: Any) -> None:
    json.dump(obj, sys.stdout, indent=2)
    print()


def _load_eval_build_with_attributes(
    client: NixbotClient, build: NixbotBuild
) -> NixbotEvalBuild:
    ev = client.load_eval_build(build)
    ev.attributes = client.resolve_attributes(ev.attribute_names)
    return ev


def _attribute_is_bad(attribute: NixbotAttribute) -> bool:
    return bool(
        attribute.build and attribute.build.status and attribute.build.status.is_bad
    )


def _eval_is_bad(ev: NixbotEvalBuild) -> bool:
    if ev.build.status and ev.build.status.is_bad:
        return True
    return any(_attribute_is_bad(a) for a in ev.attributes)


def _watch_until_complete(
    pr: PRInfo, head_sha: str, args: argparse.Namespace
) -> tuple[NixbotClient, NixbotBuild]:
    """Poll discovery until the Nixbot build is complete; emit one line per change."""
    last = ""
    while True:
        ts = datetime.now(tz=UTC).strftime("%H:%M:%S")
        try:
            client, build = _discover_eval_build(pr, head_sha)
        except CheckError as e:
            if args.json:
                _emit_json({"time": ts, "status": "WAITING", "message": str(e)})
            else:
                print(f"[{ts}] waiting: {e}", flush=True)
            time.sleep(args.interval)
            continue

        ev = client.load_eval_build(build)
        line = (
            f"[{ts}] {build.status_str:<9} #{build.number} "
            f"{build.state_string} ({len(ev.attribute_names)} attributes)"
        )
        if args.json:
            _emit_json(
                {
                    "time": ts,
                    "status": build.status_str,
                    "complete": build.complete,
                    "state_string": build.state_string,
                    "build_id": build.buildid,
                    "url": ev.web_url,
                    "attributes": len(ev.attribute_names),
                }
            )
        elif line != last:
            print(line, flush=True)
            last = line

        if build.complete:
            return client, build
        time.sleep(args.interval)


def cmd_pr(args: argparse.Namespace) -> int:
    pr = _resolve_pr(args.pr)
    head_sha = _head_sha(pr)

    if args.watch:
        client, build = _watch_until_complete(pr, head_sha, args)
    else:
        client, build = _discover_eval_build(pr, head_sha)

    ev = _load_eval_build_with_attributes(client, build)

    if args.failures:
        failures = [a for a in ev.attributes if _attribute_is_bad(a) or a.error]
        for attribute in failures:
            if not attribute.error:
                client.attach_failure_log(attribute, tail=args.log_tail)
        if args.json:
            _emit_json(
                {
                    "pr": f"{pr.owner}/{pr.repo}#{pr.pr_num}",
                    "eval_build": ev.web_url,
                    "status": ev.build.status_str,
                    "failures": [s.to_json() for s in failures],
                }
            )
        else:
            print_failures(
                cast(ReportEvalBuild, ev), cast("list[ReportAttribute]", failures)
            )
        return 1 if failures or _eval_is_bad(ev) else 0

    if args.json:
        _emit_json(
            {"pr": f"{pr.owner}/{pr.repo}#{pr.pr_num}", "eval_build": ev.to_json()}
        )
    else:
        print(f"pr: {pr.owner}/{pr.repo}#{pr.pr_num}")
        print(f"platform: {pr.platform}")
        print()
        print_eval_build(cast(ReportEvalBuild, ev))
    return 1 if _eval_is_bad(ev) else 0


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="buildbot-pr-check",
        description="Inspect Nixbot CI for a PR.",
    )
    p.add_argument("pr", nargs="?", help="PR URL or number (default: current branch)")
    p.add_argument(
        "--watch", action="store_true", help="Poll until the build completes"
    )
    p.add_argument(
        "--interval", type=int, default=60, help="Poll interval for --watch (seconds)"
    )
    p.add_argument(
        "--failures",
        action="store_true",
        help="Only failed attributes, with error and log tail",
    )
    p.add_argument(
        "--log-tail",
        type=int,
        default=80,
        help="Lines of log to tail with --failures (0=skip)",
    )
    p.add_argument(
        "--json", action="store_true", help="Emit a single JSON document on stdout"
    )
    p.add_argument("--debug", action="store_true")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    try:
        sys.exit(cmd_pr(args))
    except CheckError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
