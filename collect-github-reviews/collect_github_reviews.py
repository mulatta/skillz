#!/usr/bin/env python3
"""Collect GitHub PR review comments and repository style information.

Modes:
  user <username> <repos...>   Collect reviews by specific user
  repo <repos...>              Collect all reviews from repositories
  repo-style <repos...>        Collect repository style files
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def get_data_dir() -> Path:
    """Get the data directory for storing reviews."""
    xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg_data) / "github-reviews"


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
    # gh --paginate returns concatenated JSON arrays
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


def get_file_at_commit(repo: str, path: str, sha: str) -> str:
    """Get file content at a specific commit."""
    data = gh_api(f"/repos/{repo}/contents/{path}?ref={sha}")
    content = decode_base64_content(data)
    if content is not None:
        return content
    return f"# File not found at {sha}"


def get_repo_file(repo: str, path: str) -> str | None:
    """Get file from default branch."""
    data = gh_api(f"/repos/{repo}/contents/{path}")
    return decode_base64_content(data)


def get_pr_file_diff(repo: str, pr_number: int, path: str) -> str:
    """Get PR diff for a specific file."""
    files = gh_api(f"/repos/{repo}/pulls/{pr_number}/files")
    if isinstance(files, list):
        for f in files:
            if f.get("filename") == path:
                patch = f.get("patch")
                if isinstance(patch, str):
                    return patch
    return "# No diff available"


def save_review(
    review_dir: Path,
    comment: dict[str, Any],
    pr_info: dict[str, Any],
    repo: str,
) -> None:
    """Save a single review to disk."""
    review_dir.mkdir(parents=True, exist_ok=True)

    path = comment["path"]
    line = comment.get("line") or comment.get("original_line")
    original_line = comment.get("original_line")
    diff_hunk = comment.get("diff_hunk", "")
    body = comment.get("body", "")
    html_url = comment.get("html_url", "")
    created_at = comment.get("created_at", "")
    reviewer = comment.get("user", {}).get("login", "unknown")

    base_sha = pr_info.get("base", {}).get("sha", "")
    head_sha = pr_info.get("head", {}).get("sha", "")
    merged = pr_info.get("merged", False)
    merge_commit_sha = pr_info.get("merge_commit_sha", "")
    pr_title = pr_info.get("title", "")
    pr_number = pr_info.get("number", 0)

    # 1. Before file
    before_content = get_file_at_commit(repo, path, base_sha)
    (review_dir / "1_before.txt").write_text(before_content)

    # 2. Review metadata (JSON)
    review_json = {
        "comment_id": comment["id"],
        "pr_number": pr_number,
        "pr_title": pr_title,
        "reviewer": reviewer,
        "file": path,
        "line": line,
        "original_line": original_line,
        "created_at": created_at,
        "html_url": html_url,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "merged": merged,
        "diff_hunk": diff_hunk,
        "body": body,
    }
    (review_dir / "2_review.json").write_text(json.dumps(review_json, indent=2))

    # 2. Review markdown
    review_md = f"""# Review Comment

**PR:** #{pr_number} - {pr_title}
**Reviewer:** {reviewer}
**File:** `{path}:{line}`
**Date:** {created_at}
**URL:** {html_url}
**Merged:** {merged}

## Code Context (diff hunk)

```diff
{diff_hunk}
```

## Review Comment

{body}
"""
    (review_dir / "2_review.md").write_text(review_md)

    # 3. After file
    if merged and merge_commit_sha:
        after_content = get_file_at_commit(repo, path, merge_commit_sha)
    else:
        after_content = get_file_at_commit(repo, path, head_sha)
    (review_dir / "3_after.txt").write_text(after_content)

    # 4. Diff
    diff_content = get_pr_file_diff(repo, pr_number, path)
    (review_dir / "4_diff.patch").write_text(diff_content)


def collect_reviews(
    repo: str,
    output_dir: Path,
    filter_user: str | None = None,
) -> None:
    """Collect reviews from a repository."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if filter_user:
        print(f"=== Collecting reviews from {repo} for user {filter_user} ===")
    else:
        print(f"=== Collecting all reviews from {repo} ===")

    # Fetch all review comments
    comments = gh_api_paginate(f"/repos/{repo}/pulls/comments?per_page=100")

    if filter_user:
        comments = [
            c for c in comments if c.get("user", {}).get("login") == filter_user
        ]

    print(f"Found {len(comments)} review comments")

    if not comments:
        print("No reviews found")
        return

    # Save raw comments
    raw_file = output_dir / "_raw_comments.json"
    raw_file.write_text(json.dumps(comments, indent=2))

    # Cache PR info
    pr_cache: dict[int, dict[str, Any]] = {}

    for i, comment in enumerate(comments):
        comment_id = comment["id"]
        pr_url = comment["pull_request_url"]
        pr_number = int(pr_url.split("/")[-1])
        path = comment["path"]
        line = comment.get("line") or comment.get("original_line")
        reviewer = comment.get("user", {}).get("login", "unknown")

        print(
            f"  [{i + 1}/{len(comments)}] PR#{pr_number} - {path}:{line} ({reviewer})"
        )

        # Get PR info (cached)
        if pr_number not in pr_cache:
            pr_info = gh_api(f"/repos/{repo}/pulls/{pr_number}")
            pr_cache[pr_number] = pr_info if isinstance(pr_info, dict) else {}
        pr_info = pr_cache[pr_number]

        review_dir = output_dir / f"pr{pr_number}_{comment_id}"
        save_review(review_dir, comment, pr_info, repo)

    print()
    print(f"Completed: {repo} ({len(comments)} reviews)")
    print(f"  Output: {output_dir}")


def collect_repo_style(repo: str, data_dir: Path) -> None:
    """Collect repository style files."""
    repo_safe = repo.replace("/", "_")
    style_dir = data_dir / "repos" / repo_safe / "style"
    style_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Collecting style files from {repo} ===")

    style_files = [
        ".editorconfig",
        ".prettierrc",
        ".prettierrc.json",
        ".prettierrc.yaml",
        ".eslintrc.json",
        ".eslintrc.yaml",
        "treefmt.toml",
        ".treefmt.toml",
        "rustfmt.toml",
        ".rustfmt.toml",
        "pyproject.toml",
        "flake.nix",
        ".github/CONTRIBUTING.md",
        "CONTRIBUTING.md",
        ".clang-format",
        ".stylua.toml",
        "stylua.toml",
    ]

    found = 0
    for file in style_files:
        content = get_repo_file(repo, file)
        if content:
            safe_name = file.replace("/", "_")
            (style_dir / safe_name).write_text(content)
            print(f"  Found: {file}")
            found += 1

    # Get repo languages
    languages = gh_api(f"/repos/{repo}/languages")
    if isinstance(languages, dict):
        (style_dir / "_languages.json").write_text(json.dumps(languages, indent=2))
        print(f"  Languages: {', '.join(languages.keys())}")

    print()
    print(f"Completed: {repo} ({found} style files)")
    print(f"  Output: {style_dir}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Collect GitHub PR review comments and repository style information.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Output structure:
  ~/.local/share/github-reviews/
  ├── users/<username>/<repo>/   # User-specific reviews
  └── repos/<repo>/
      ├── reviews/               # All reviewers' comments
      └── style/                 # .editorconfig, treefmt, etc.

Examples:
  %(prog)s user Mic92 numtide/llm-agents.nix
  %(prog)s repo NixOS/nixpkgs
  %(prog)s repo-style numtide/llm-agents.nix
""",
    )

    subparsers = parser.add_subparsers(dest="mode", required=True)

    # user mode
    user_parser = subparsers.add_parser("user", help="Collect reviews by specific user")
    user_parser.add_argument("username", help="GitHub username")
    user_parser.add_argument("repos", nargs="+", help="Repositories (owner/repo)")

    # repo mode
    repo_parser = subparsers.add_parser(
        "repo", help="Collect all reviews from repositories"
    )
    repo_parser.add_argument("repos", nargs="+", help="Repositories (owner/repo)")

    # repo-style mode
    style_parser = subparsers.add_parser(
        "repo-style", help="Collect repository style files"
    )
    style_parser.add_argument("repos", nargs="+", help="Repositories (owner/repo)")

    args = parser.parse_args()
    data_dir = get_data_dir()

    if args.mode == "user":
        print("GitHub Review Collector (User Mode)")
        print(f"User: {args.username}")
        print(f"Repos: {' '.join(args.repos)}")
        print()

        for repo in args.repos:
            repo_safe = repo.replace("/", "_")
            output_dir = data_dir / "users" / args.username / repo_safe
            collect_reviews(repo, output_dir, args.username)
            print()

        print("=== Done ===")
        print(f"Output: {data_dir / 'users' / args.username}/")

    elif args.mode == "repo":
        print("GitHub Review Collector (Repo Mode)")
        print(f"Repos: {' '.join(args.repos)}")
        print()

        for repo in args.repos:
            repo_safe = repo.replace("/", "_")
            output_dir = data_dir / "repos" / repo_safe / "reviews"
            collect_reviews(repo, output_dir)
            print()

        print("=== Done ===")
        print(f"Output: {data_dir / 'repos'}/")

    elif args.mode == "repo-style":
        print("GitHub Style Collector")
        print(f"Repos: {' '.join(args.repos)}")
        print()

        for repo in args.repos:
            collect_repo_style(repo, data_dir)
            print()

        print("=== Done ===")
        print(f"Output: {data_dir / 'repos'}/")


if __name__ == "__main__":
    main()
