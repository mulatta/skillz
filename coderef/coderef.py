#!/usr/bin/env python3
"""Collect GitHub PR code changes for ck/qmd semantic search indexing.

Usage:
  # Single PR
  coderef collect <repo> <pr-number>
  coderef collect NixOS/nixpkgs 249259

  # PRs authored by user
  coderef collect <repo> --author <user> [--limit N] [--state merged]
  coderef collect NixOS/nixpkgs --author Mic92 --limit 50

  # PRs reviewed by user
  coderef collect <repo> --reviewer <user> [--limit N] [--state merged]
  coderef collect NixOS/nixpkgs --reviewer Mic92 --limit 50

  # With date filter and caching
  coderef collect NixOS/nixpkgs --author Mic92 --since 1y --skip-existing
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def get_data_dir(custom_path: str | None = None) -> Path:
    """Get the base data directory for coderef."""
    if custom_path:
        return Path(custom_path).expanduser()
    xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg_data) / "coderef"


def get_bundle_dir(
    repo: str,
    pr_number: int,
    base_dir: Path,
    role: str | None = None,
    user: str | None = None,
) -> Path:
    """Get the bundle directory path based on role.

    Args:
        repo: Repository in owner/repo format
        pr_number: PR number
        base_dir: Base data directory
        role: "authored", "reviewed", or None for single PR
        user: Username (required if role is set)

    Returns:
        Path like:
        - authored/<user>/<repo>/pr<N>/
        - reviewed/<user>/<repo>/pr<N>/
        - prs/<repo>/pr<N>/  (when role is None)
    """
    repo_slug = repo.replace("/", "_")

    if role and user:
        return base_dir / role / user / repo_slug / f"pr{pr_number}"
    return base_dir / "prs" / repo_slug / f"pr{pr_number}"


def gh_api(endpoint: str) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Call GitHub API via gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
            check=True,
        )
        data: dict[str, Any] | list[dict[str, Any]] = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None
    return data


def gh_api_paginate(endpoint: str) -> list[dict[str, Any]]:
    """Call GitHub API with pagination."""
    try:
        result = subprocess.run(
            ["gh", "api", "--paginate", endpoint],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return []
    items: list[dict[str, Any]] = []
    for line in result.stdout.strip().split("\n"):
        if line:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, list):
                items.extend(data)
            elif isinstance(data, dict):
                items.append(data)
    return items


def decode_base64_content(
    data: dict[str, Any] | list[dict[str, Any]] | None,
) -> str | None:
    """Decode base64 content from GitHub API response."""
    if not isinstance(data, dict):
        return None
    content = data.get("content")
    if not isinstance(content, str):
        return None
    try:
        decoded = base64.b64decode(content).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return decoded


def get_file_at_ref(repo: str, path: str, ref: str) -> str | None:
    """Get file content at a specific git ref (commit, branch, tag)."""
    data = gh_api(f"/repos/{repo}/contents/{path}?ref={ref}")
    return decode_base64_content(data)


def is_bot(user: dict[str, Any]) -> bool:
    """Check if user is a bot account.

    Only uses:
    - GitHub API type field
    - [bot] suffix convention
    """
    if user.get("type") == "Bot":
        return True
    login = user.get("login", "")
    if login.endswith("[bot]"):
        return True
    return False


def get_file_extension(path: str) -> str:
    """Get file extension for syntax highlighting."""
    ext_map = {
        ".nix": "nix",
        ".py": "python",
        ".rs": "rust",
        ".go": "go",
        ".js": "javascript",
        ".ts": "typescript",
        ".sh": "bash",
        ".md": "markdown",
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return ""


def save_docs(
    bundle_dir: Path,
    pr_data: dict[str, Any],
    repo: str,
    pr_number: int,
    exclude_bots: bool = True,
) -> dict[str, int]:
    """Fetch and save documentation (PR body, comments, reviews).

    Returns dict with counts of saved documents.
    """
    docs_dir = bundle_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    counts = {"summary": 0, "comments": 0, "reviews": 0, "discussion": 0}

    # 1. Save PR summary (body)
    title = pr_data.get("title", "")
    body = pr_data.get("body") or ""
    author = pr_data.get("user", {}).get("login", "")
    state = pr_data.get("state", "")
    merged = pr_data.get("merged", False)
    merged_at = pr_data.get("merged_at") or ""
    labels = [label.get("name", "") for label in pr_data.get("labels", [])]
    url = pr_data.get("html_url", "")

    summary_content = f"""# {title}

Author: {author} | State: {state} | Merged: {merged}
{f"Merged at: {merged_at}" if merged_at else ""}
Labels: {", ".join(labels) if labels else "(none)"}
URL: {url}

## Description

{body}
"""
    (docs_dir / "summary.md").write_text(summary_content)
    counts["summary"] = 1

    # 2. Fetch and save line comments (code-linked)
    comments_dir = docs_dir / "comments"
    comments_dir.mkdir(exist_ok=True)

    line_comments = gh_api_paginate(f"/repos/{repo}/pulls/{pr_number}/comments")
    for comment in line_comments:
        user = comment.get("user", {})
        if exclude_bots and is_bot(user):
            continue

        comment_id = comment.get("id", 0)
        commenter = user.get("login", "unknown")
        path = comment.get("path", "")
        line = comment.get("line") or comment.get("original_line") or "?"
        side = comment.get("side", "RIGHT")
        diff_hunk = comment.get("diff_hunk", "")
        comment_body = comment.get("body", "")
        lang = get_file_extension(path)

        comment_content = f"""# Comment by {commenter}

File: `{path}` | Line: {line} | Side: {side}

## Code Context

```{lang}
{diff_hunk}
```

## Feedback

{comment_body}
"""
        (comments_dir / f"comment-{comment_id}.md").write_text(comment_content)
        counts["comments"] += 1

    # 3. Fetch and save review summaries
    reviews_dir = docs_dir / "reviews"
    reviews_dir.mkdir(exist_ok=True)

    reviews = gh_api_paginate(f"/repos/{repo}/pulls/{pr_number}/reviews")
    for review in reviews:
        user = review.get("user", {})
        if exclude_bots and is_bot(user):
            continue

        review_id = review.get("id", 0)
        reviewer = user.get("login", "unknown")
        review_state = review.get("state", "")
        review_body = review.get("body") or ""
        submitted_at = review.get("submitted_at", "")

        # Skip empty reviews (just approvals without comments)
        if not review_body and review_state == "APPROVED":
            continue

        review_content = f"""# Review by {reviewer}

State: {review_state}
Submitted: {submitted_at}

## Summary

{review_body if review_body else "(No summary provided)"}
"""
        (reviews_dir / f"review-{review_id}.md").write_text(review_content)
        counts["reviews"] += 1

    # 4. Fetch and save discussion comments (issue comments)
    discussion_dir = docs_dir / "discussion"
    discussion_dir.mkdir(exist_ok=True)

    discussion = gh_api_paginate(f"/repos/{repo}/issues/{pr_number}/comments")
    for comment in discussion:
        user = comment.get("user", {})
        if exclude_bots and is_bot(user):
            continue

        comment_id = comment.get("id", 0)
        commenter = user.get("login", "unknown")
        created_at = comment.get("created_at", "")
        comment_body = comment.get("body", "")

        disc_content = f"""# Comment by {commenter}

Date: {created_at}

{comment_body}
"""
        (discussion_dir / f"disc-{comment_id}.md").write_text(disc_content)
        counts["discussion"] += 1

    return counts


def parse_since(since: str | None) -> str | None:
    """Parse --since argument to date string for GitHub API.

    Accepts:
    - ISO date: 2024-01-01
    - Relative: 1y, 6m, 30d

    Returns: ISO date string or None
    """
    if not since:
        return None

    import re
    from datetime import datetime, timedelta

    # Already ISO format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", since):
        return since

    # Relative format
    match = re.match(r"^(\d+)([ymd])$", since)
    if match:
        num = int(match.group(1))
        unit = match.group(2)
        now = datetime.now()
        if unit == "y":
            delta = timedelta(days=num * 365)
        elif unit == "m":
            delta = timedelta(days=num * 30)
        else:  # d
            delta = timedelta(days=num)
        return (now - delta).strftime("%Y-%m-%d")

    return None


def list_authored_prs(
    repo: str,
    author: str,
    limit: int = 100,
    state: str = "all",
    since: str | None = None,
) -> list[int]:
    """List PR numbers authored by a user.

    Args:
        repo: Repository in owner/repo format
        author: GitHub username
        limit: Maximum number of PRs to return
        state: PR state filter (all, open, closed, merged)
        since: Only PRs created after this date (ISO or relative like 1y, 6m)
    """
    cmd = [
        "gh",
        "search",
        "prs",
        "--repo",
        repo,
        "--author",
        author,
        "--limit",
        str(limit),
        "--json",
        "number",
    ]
    # gh search prs: --state only accepts open|closed, use --merged for merged
    if state == "merged":
        cmd.append("--merged")
    elif state in ("open", "closed"):
        cmd.extend(["--state", state])
    # state == "all": no filter, search returns both open and closed

    # Date filter
    since_date = parse_since(since)
    if since_date:
        cmd.extend(["--created", f">={since_date}"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []

    return [pr["number"] for pr in data if "number" in pr]


def list_reviewed_prs(
    repo: str,
    reviewer: str,
    limit: int = 100,
    state: str = "all",
    since: str | None = None,
) -> list[int]:
    """List PR numbers reviewed by a user.

    Args:
        repo: Repository in owner/repo format
        reviewer: GitHub username
        limit: Maximum number of PRs to return
        state: PR state filter (all, open, closed, merged)
        since: Only PRs created after this date (ISO or relative like 1y, 6m)
    """
    cmd = [
        "gh",
        "search",
        "prs",
        "--repo",
        repo,
        "--reviewed-by",
        reviewer,
        "--limit",
        str(limit),
        "--json",
        "number",
    ]
    if state == "merged":
        cmd.append("--merged")
    elif state in ("open", "closed"):
        cmd.extend(["--state", state])

    # Date filter
    since_date = parse_since(since)
    if since_date:
        cmd.extend(["--created", f">={since_date}"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []

    return [pr["number"] for pr in data if "number" in pr]


def collect_pr(
    repo: str,
    pr_number: int,
    base_dir: Path,
    role: str | None = None,
    user: str | None = None,
    exclude_bots: bool = True,
) -> bool:
    """Collect PR data and create bundle.

    Args:
        repo: Repository in owner/repo format
        pr_number: PR number
        base_dir: Base data directory
        role: "authored", "reviewed", or None for single PR
        user: Username (required if role is set)
        exclude_bots: Filter out bot comments

    Returns True on success, False on failure.
    """
    print(f"Fetching PR #{pr_number} from {repo}...", file=sys.stderr)

    # 1. Fetch PR metadata
    pr_data = gh_api(f"/repos/{repo}/pulls/{pr_number}")
    if not isinstance(pr_data, dict):
        print(f"Error: Could not fetch PR #{pr_number}", file=sys.stderr)
        return False

    # Extract key metadata
    head_sha = pr_data.get("head", {}).get("sha", "")
    base_sha = pr_data.get("base", {}).get("sha", "")
    if not head_sha:
        print("Error: Could not determine head SHA", file=sys.stderr)
        return False

    # 2. Fetch changed files
    files_data = gh_api_paginate(f"/repos/{repo}/pulls/{pr_number}/files")
    if not files_data:
        print("Warning: No files found in PR", file=sys.stderr)

    # Create bundle directory
    bundle_dir = get_bundle_dir(repo, pr_number, base_dir, role, user)
    code_dir = bundle_dir / "code"
    diffs_dir = bundle_dir / "diffs"

    code_dir.mkdir(parents=True, exist_ok=True)
    diffs_dir.mkdir(parents=True, exist_ok=True)

    # 3. Build metadata
    meta: dict[str, Any] = {
        "repo": repo,
        "pr_number": pr_number,
        "title": pr_data.get("title", ""),
        "author": pr_data.get("user", {}).get("login", ""),
        "state": pr_data.get("state", ""),
        "merged": pr_data.get("merged", False),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "merge_commit_sha": pr_data.get("merge_commit_sha"),
        "created_at": pr_data.get("created_at", ""),
        "merged_at": pr_data.get("merged_at"),
        "labels": [label.get("name", "") for label in pr_data.get("labels", [])],
        "url": pr_data.get("html_url", ""),
        "files": [],
    }
    if role and user:
        meta["collection_role"] = role
        meta["collected_for"] = user

    # 4. Fetch and save each file
    for file_info in files_data:
        filename = file_info.get("filename", "")
        status = file_info.get("status", "")
        patch = file_info.get("patch", "")

        if not filename:
            continue

        # Skip binary files (no patch available)
        if (
            status not in ("removed",)
            and not patch
            and file_info.get("additions", 0) > 0
        ):
            print(f"  Skipping binary: {filename}", file=sys.stderr)
            continue

        meta["files"].append(
            {
                "path": filename,
                "status": status,
                "additions": file_info.get("additions", 0),
                "deletions": file_info.get("deletions", 0),
            }
        )

        # Safe filename for filesystem
        safe_name = filename.replace("/", "__")

        # Save patch/diff
        if patch:
            diff_path = diffs_dir / f"{safe_name}.patch"
            diff_path.write_text(patch)

        # Fetch file content at head (for added/modified files)
        if status in ("added", "modified", "renamed", "copied"):
            content = get_file_at_ref(repo, filename, head_sha)
            if content:
                code_path = code_dir / safe_name
                code_path.write_text(content)
                print(f"  Saved: {filename}", file=sys.stderr)

    # 5. Save documentation (PR body, comments, reviews)
    doc_counts = save_docs(bundle_dir, pr_data, repo, pr_number, exclude_bots)
    meta["doc_counts"] = doc_counts

    # 6. Save metadata
    meta_path = bundle_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    print(
        f"Bundle created: {bundle_dir} "
        f"(docs: {doc_counts['comments']} comments, "
        f"{doc_counts['reviews']} reviews, "
        f"{doc_counts['discussion']} discussion)",
        file=sys.stderr,
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect GitHub PR code changes for semantic search indexing",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # collect subcommand
    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect PR code and metadata into a bundle",
    )
    collect_parser.add_argument(
        "repo",
        help="Repository in owner/repo format (e.g., NixOS/nixpkgs)",
    )
    collect_parser.add_argument(
        "pr_number",
        type=int,
        nargs="?",
        default=None,
        help="Pull request number (required unless --author or --reviewer is specified)",
    )
    collect_parser.add_argument(
        "--author",
        help="Collect PRs authored by this user",
    )
    collect_parser.add_argument(
        "--reviewer",
        help="Collect PRs reviewed by this user",
    )
    collect_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of PRs to collect (default: 50)",
    )
    collect_parser.add_argument(
        "--state",
        choices=["all", "open", "closed", "merged"],
        default="merged",
        help="PR state filter (default: merged)",
    )
    collect_parser.add_argument(
        "--output",
        "-o",
        help="Output directory (default: ~/.local/share/coderef)",
    )
    collect_parser.add_argument(
        "--since",
        help="Only collect PRs created after this date (e.g., 2024-01-01 or 1y, 6m, 30d)",
    )
    collect_parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip PRs that have already been collected",
    )
    collect_parser.add_argument(
        "--exclude-bots",
        action="store_true",
        default=True,
        help="Exclude bot comments (default: true)",
    )
    collect_parser.add_argument(
        "--include-bots",
        action="store_true",
        help="Include bot comments",
    )

    args = parser.parse_args()

    if args.command == "collect":
        base_dir = get_data_dir(args.output)
        exclude_bots = not args.include_bots  # --include-bots overrides default

        # Validate arguments
        if args.author and args.reviewer:
            print("Error: Cannot specify both --author and --reviewer", file=sys.stderr)
            return 1

        if args.pr_number is not None:
            # Single PR mode
            if args.author or args.reviewer:
                print(
                    "Error: Cannot specify PR number with --author or --reviewer",
                    file=sys.stderr,
                )
                return 1
            success = collect_pr(
                args.repo, args.pr_number, base_dir, exclude_bots=exclude_bots
            )
            return 0 if success else 1

        if args.author:
            # Authored PRs mode
            pr_numbers = list_authored_prs(
                args.repo, args.author, args.limit, args.state, args.since
            )
            if not pr_numbers:
                print(
                    f"No PRs found by author {args.author} in {args.repo}",
                    file=sys.stderr,
                )
                return 1
            print(f"Found {len(pr_numbers)} PRs by {args.author}", file=sys.stderr)
            success_count = 0
            skipped_count = 0
            for pr_num in pr_numbers:
                bundle_dir = get_bundle_dir(
                    args.repo, pr_num, base_dir, "authored", args.author
                )
                if args.skip_existing and bundle_dir.exists():
                    skipped_count += 1
                    continue
                if collect_pr(
                    args.repo, pr_num, base_dir, "authored", args.author, exclude_bots
                ):
                    success_count += 1
            print(
                f"Collected {success_count}/{len(pr_numbers)} PRs "
                f"(skipped {skipped_count} existing)",
                file=sys.stderr,
            )
            return 0 if success_count > 0 or skipped_count > 0 else 1

        if args.reviewer:
            # Reviewed PRs mode
            pr_numbers = list_reviewed_prs(
                args.repo, args.reviewer, args.limit, args.state, args.since
            )
            if not pr_numbers:
                print(
                    f"No PRs reviewed by {args.reviewer} in {args.repo}",
                    file=sys.stderr,
                )
                return 1
            print(
                f"Found {len(pr_numbers)} PRs reviewed by {args.reviewer}",
                file=sys.stderr,
            )
            success_count = 0
            skipped_count = 0
            for pr_num in pr_numbers:
                bundle_dir = get_bundle_dir(
                    args.repo, pr_num, base_dir, "reviewed", args.reviewer
                )
                if args.skip_existing and bundle_dir.exists():
                    skipped_count += 1
                    continue
                if collect_pr(
                    args.repo, pr_num, base_dir, "reviewed", args.reviewer, exclude_bots
                ):
                    success_count += 1
            print(
                f"Collected {success_count}/{len(pr_numbers)} PRs "
                f"(skipped {skipped_count} existing)",
                file=sys.stderr,
            )
            return 0 if success_count > 0 or skipped_count > 0 else 1

        print("Error: Must specify PR number or --author/--reviewer", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
