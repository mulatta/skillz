#!/usr/bin/env python3
"""Collect GitHub PR data for style analysis and code review.

Usage:
  # Single PR
  style-review collect <repo> <pr-number>
  style-review collect NixOS/nixpkgs 249259

  # PRs authored by user
  style-review collect <repo> --author <user> [--limit N] [--state merged]
  style-review collect NixOS/nixpkgs --author Mic92 --limit 50

  # PRs reviewed by user
  style-review collect <repo> --reviewer <user> [--limit N] [--state merged]
  style-review collect NixOS/nixpkgs --reviewer Mic92 --limit 50

  # With date filter and caching
  style-review collect NixOS/nixpkgs --author Mic92 --since 1y --skip-existing

  # Query database
  style-review query "SELECT * FROM prs WHERE author = 'ConnorBaker'"

  # Database management
  style-review db schema    # Show database schema
  style-review db migrate   # Migrate existing data to new structure

Pattern analysis is done by the /style skill using ast-grep, ck, and qmd.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# SQLite schema
SCHEMA = """
-- Repositories
CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE(owner, name)
);

-- Pull Requests
CREATE TABLE IF NOT EXISTS prs (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL REFERENCES repos(id),
    number INTEGER NOT NULL,
    title TEXT,
    author TEXT NOT NULL,
    state TEXT,
    merged INTEGER DEFAULT 0,
    created_at TEXT,
    merged_at TEXT,
    labels TEXT,
    url TEXT,
    file_path TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    UNIQUE(repo_id, number)
);

-- PR Participants (author + reviewers + commenters)
CREATE TABLE IF NOT EXISTS pr_participants (
    pr_id INTEGER NOT NULL REFERENCES prs(id),
    user TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (pr_id, user, role)
);

-- Comments metadata
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    pr_id INTEGER NOT NULL REFERENCES prs(id),
    github_id INTEGER NOT NULL,
    author TEXT NOT NULL,
    comment_type TEXT NOT NULL,
    file_path TEXT,
    line_number INTEGER,
    created_at TEXT,
    is_bot INTEGER DEFAULT 0,
    UNIQUE(pr_id, github_id)
);

-- Changed files in PR
CREATE TABLE IF NOT EXISTS pr_files (
    pr_id INTEGER NOT NULL REFERENCES prs(id),
    file_path TEXT NOT NULL,
    change_type TEXT,
    additions INTEGER DEFAULT 0,
    deletions INTEGER DEFAULT 0,
    PRIMARY KEY (pr_id, file_path)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_prs_author ON prs(author);
CREATE INDEX IF NOT EXISTS idx_prs_repo ON prs(repo_id);
CREATE INDEX IF NOT EXISTS idx_participants_user ON pr_participants(user);
CREATE INDEX IF NOT EXISTS idx_participants_role ON pr_participants(user, role);
CREATE INDEX IF NOT EXISTS idx_comments_author ON comments(author);
CREATE INDEX IF NOT EXISTS idx_comments_type ON comments(comment_type);
"""


def get_data_dir(custom_path: str | None = None) -> Path:
    """Get the base data directory for style-review."""
    if custom_path:
        return Path(custom_path).expanduser()
    xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg_data) / "style-review"


def get_db_path(base_dir: Path) -> Path:
    """Get the SQLite database path."""
    return base_dir / "style-review.db"


def get_db(base_dir: Path) -> sqlite3.Connection:
    """Get database connection, creating tables if needed."""
    db_path = get_db_path(base_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_files_dir(base_dir: Path) -> Path:
    """Get the files directory for storing PR content."""
    return base_dir / "files"


def get_pr_dir(repo: str, pr_number: int, base_dir: Path) -> Path:
    """Get the PR directory path.

    New structure: files/<owner_repo>/pr<N>/
    """
    repo_slug = repo.replace("/", "_")
    return get_files_dir(base_dir) / repo_slug / f"pr{pr_number}"


def get_or_create_repo(conn: sqlite3.Connection, repo: str) -> int:
    """Get or create repo entry, return repo_id."""
    owner, name = repo.split("/", 1)
    cursor = conn.execute(
        "SELECT id FROM repos WHERE owner = ? AND name = ?",
        (owner, name),
    )
    row = cursor.fetchone()
    if row:
        return row["id"]

    cursor = conn.execute(
        "INSERT INTO repos (owner, name) VALUES (?, ?)",
        (owner, name),
    )
    repo_id: int = cursor.lastrowid  # type: ignore[assignment]
    return repo_id


def pr_exists(conn: sqlite3.Connection, repo_id: int, pr_number: int) -> bool:
    """Check if PR already exists in database."""
    cursor = conn.execute(
        "SELECT 1 FROM prs WHERE repo_id = ? AND number = ?",
        (repo_id, pr_number),
    )
    return cursor.fetchone() is not None


def get_pr_id(conn: sqlite3.Connection, repo_id: int, pr_number: int) -> int | None:
    """Get PR ID from database."""
    cursor = conn.execute(
        "SELECT id FROM prs WHERE repo_id = ? AND number = ?",
        (repo_id, pr_number),
    )
    row = cursor.fetchone()
    return row["id"] if row else None


def add_participant(conn: sqlite3.Connection, pr_id: int, user: str, role: str) -> None:
    """Add participant to PR (idempotent)."""
    conn.execute(
        "INSERT OR IGNORE INTO pr_participants (pr_id, user, role) VALUES (?, ?, ?)",
        (pr_id, user, role),
    )


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


def is_bot(user: dict[str, Any] | None) -> bool:
    """Check if user is a bot account."""
    if user is None:
        return False
    return user.get("type") == "Bot" or user.get("login", "").endswith("[bot]")


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
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Fetch and save documentation (PR body, comments, reviews).

    Returns (counts dict, list of comment metadata for DB).
    """
    docs_dir = bundle_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    counts = {"summary": 0, "comments": 0, "reviews": 0, "discussion": 0}
    comment_records: list[dict[str, Any]] = []

    # 1. Save PR summary (body)
    title = pr_data.get("title", "")
    body = pr_data.get("body") or ""
    author = (pr_data.get("user") or {}).get("login", "")
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
        user = comment.get("user") or {}
        user_is_bot = is_bot(user)
        if exclude_bots and user_is_bot:
            continue

        comment_id = comment.get("id", 0)
        commenter = user.get("login", "unknown") if user else "unknown"
        path = comment.get("path", "")
        line = comment.get("line") or comment.get("original_line") or 0
        side = comment.get("side", "RIGHT")
        diff_hunk = comment.get("diff_hunk", "")
        comment_body = comment.get("body", "")
        created_at = comment.get("created_at", "")
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

        comment_records.append(
            {
                "github_id": comment_id,
                "author": commenter,
                "comment_type": "line_comment",
                "file_path": path,
                "line_number": line if isinstance(line, int) else None,
                "created_at": created_at,
                "is_bot": 1 if user_is_bot else 0,
            }
        )

    # 3. Fetch and save review summaries
    reviews_dir = docs_dir / "reviews"
    reviews_dir.mkdir(exist_ok=True)

    reviews = gh_api_paginate(f"/repos/{repo}/pulls/{pr_number}/reviews")
    for review in reviews:
        user = review.get("user") or {}
        user_is_bot = is_bot(user)
        if exclude_bots and user_is_bot:
            continue

        review_id = review.get("id", 0)
        reviewer = user.get("login", "unknown") if user else "unknown"
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

        comment_records.append(
            {
                "github_id": review_id,
                "author": reviewer,
                "comment_type": "review",
                "file_path": None,
                "line_number": None,
                "created_at": submitted_at,
                "is_bot": 1 if user_is_bot else 0,
            }
        )

    # 4. Fetch and save discussion comments (issue comments)
    discussion_dir = docs_dir / "discussion"
    discussion_dir.mkdir(exist_ok=True)

    discussion = gh_api_paginate(f"/repos/{repo}/issues/{pr_number}/comments")
    for comment in discussion:
        user = comment.get("user") or {}
        user_is_bot = is_bot(user)
        if exclude_bots and user_is_bot:
            continue

        comment_id = comment.get("id", 0)
        commenter = user.get("login", "unknown") if user else "unknown"
        created_at = comment.get("created_at", "")
        comment_body = comment.get("body", "")

        disc_content = f"""# Comment by {commenter}

Date: {created_at}

{comment_body}
"""
        (discussion_dir / f"disc-{comment_id}.md").write_text(disc_content)
        counts["discussion"] += 1

        comment_records.append(
            {
                "github_id": comment_id,
                "author": commenter,
                "comment_type": "discussion",
                "file_path": None,
                "line_number": None,
                "created_at": created_at,
                "is_bot": 1 if user_is_bot else 0,
            }
        )

    return counts, comment_records


def parse_since(since: str | None) -> str | None:
    """Parse --since argument to date string for GitHub API."""
    if not since:
        return None

    if re.match(r"^\d{4}-\d{2}-\d{2}$", since):
        return since

    match = re.match(r"^(\d+)([ymd])$", since)
    if match:
        num = int(match.group(1))
        unit = match.group(2)
        now = datetime.now(UTC)
        if unit == "y":
            delta = timedelta(days=num * 365)
        elif unit == "m":
            delta = timedelta(days=num * 30)
        else:
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
    """List PR numbers authored by a user."""
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
    if state == "merged":
        cmd.append("--merged")
    elif state in ("open", "closed"):
        cmd.extend(["--state", state])

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
    """List PR numbers reviewed by a user."""
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
    conn: sqlite3.Connection,
    role: str | None = None,
    user: str | None = None,
    exclude_bots: bool = True,
) -> bool:
    """Collect PR data and create bundle.

    If PR already exists, only adds participant if role/user specified.
    """
    repo_id = get_or_create_repo(conn, repo)

    # Check if PR already exists
    existing_pr_id = get_pr_id(conn, repo_id, pr_number)
    if existing_pr_id:
        # PR already collected - just add participant
        if role and user:
            add_participant(
                conn, existing_pr_id, user, role.rstrip("ed")
            )  # authored -> author
            conn.commit()
            print(
                f"PR #{pr_number} already exists, added {user} as {role}",
                file=sys.stderr,
            )
        return True

    print(f"Fetching PR #{pr_number} from {repo}...", file=sys.stderr)

    # 1. Fetch PR metadata
    pr_data = gh_api(f"/repos/{repo}/pulls/{pr_number}")
    if not isinstance(pr_data, dict):
        print(f"Error: Could not fetch PR #{pr_number}", file=sys.stderr)
        return False

    head_sha = pr_data.get("head", {}).get("sha", "")
    base_sha = pr_data.get("base", {}).get("sha", "")
    if not head_sha:
        print("Error: Could not determine head SHA", file=sys.stderr)
        return False

    # 2. Fetch changed files
    files_data = gh_api_paginate(f"/repos/{repo}/pulls/{pr_number}/files")

    # Create bundle directory (new structure)
    bundle_dir = get_pr_dir(repo, pr_number, base_dir)
    code_dir = bundle_dir / "code"
    diffs_dir = bundle_dir / "diffs"

    code_dir.mkdir(parents=True, exist_ok=True)
    diffs_dir.mkdir(parents=True, exist_ok=True)

    # 3. Build metadata
    pr_author = (pr_data.get("user") or {}).get("login", "")
    pr_title = pr_data.get("title", "")
    pr_state = pr_data.get("state", "")
    pr_merged = pr_data.get("merged", False)
    pr_created_at = pr_data.get("created_at", "")
    pr_merged_at = pr_data.get("merged_at")
    pr_labels = json.dumps(
        [label.get("name", "") for label in pr_data.get("labels", [])]
    )
    pr_url = pr_data.get("html_url", "")
    repo_slug = repo.replace("/", "_")
    file_path = f"{repo_slug}/pr{pr_number}"

    file_records: list[dict[str, Any]] = []

    # 4. Fetch and save each file
    for file_info in files_data:
        filename = file_info.get("filename", "")
        status = file_info.get("status", "")
        patch = file_info.get("patch", "")
        additions = file_info.get("additions", 0)
        deletions = file_info.get("deletions", 0)

        if not filename:
            continue

        # Skip binary files
        if status not in ("removed",) and not patch and additions > 0:
            print(f"  Skipping binary: {filename}", file=sys.stderr)
            continue

        file_records.append(
            {
                "file_path": filename,
                "change_type": status,
                "additions": additions,
                "deletions": deletions,
            }
        )

        safe_name = filename.replace("/", "__")

        if patch:
            diff_path = diffs_dir / f"{safe_name}.patch"
            diff_path.write_text(patch)

        if status in ("added", "modified", "renamed", "copied"):
            content = get_file_at_ref(repo, filename, head_sha)
            if content:
                code_path = code_dir / safe_name
                code_path.write_text(content)
                print(f"  Saved: {filename}", file=sys.stderr)

    # 5. Save documentation
    doc_counts, comment_records = save_docs(
        bundle_dir, pr_data, repo, pr_number, exclude_bots
    )

    # 6. Save metadata JSON (for compatibility)
    meta: dict[str, Any] = {
        "repo": repo,
        "pr_number": pr_number,
        "title": pr_title,
        "author": pr_author,
        "state": pr_state,
        "merged": pr_merged,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "merge_commit_sha": pr_data.get("merge_commit_sha"),
        "created_at": pr_created_at,
        "merged_at": pr_merged_at,
        "labels": json.loads(pr_labels),
        "url": pr_url,
        "files": [f["file_path"] for f in file_records],
        "doc_counts": doc_counts,
    }
    (bundle_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # 7. Insert into database
    cursor = conn.execute(
        """INSERT INTO prs
           (repo_id, number, title, author, state, merged, created_at, merged_at,
            labels, url, file_path, collected_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            repo_id,
            pr_number,
            pr_title,
            pr_author,
            pr_state,
            1 if pr_merged else 0,
            pr_created_at,
            pr_merged_at,
            pr_labels,
            pr_url,
            file_path,
            datetime.now(UTC).isoformat(),
        ),
    )
    pr_id: int = cursor.lastrowid  # type: ignore[assignment]

    # Add author as participant
    add_participant(conn, pr_id, pr_author, "author")

    # Add requesting user as participant if specified
    if role and user:
        participant_role = "author" if role == "authored" else "reviewer"
        add_participant(conn, pr_id, user, participant_role)

    # Extract reviewers from comments and add as participants
    reviewers = set()
    for comment in comment_records:
        if comment["author"] != pr_author:
            reviewers.add(comment["author"])

    for reviewer in reviewers:
        add_participant(conn, pr_id, reviewer, "reviewer")

    # Insert files
    for file_rec in file_records:
        conn.execute(
            """INSERT OR IGNORE INTO pr_files
               (pr_id, file_path, change_type, additions, deletions)
               VALUES (?, ?, ?, ?, ?)""",
            (
                pr_id,
                file_rec["file_path"],
                file_rec["change_type"],
                file_rec["additions"],
                file_rec["deletions"],
            ),
        )

    # Insert comments
    for comment in comment_records:
        conn.execute(
            """INSERT OR IGNORE INTO comments
               (pr_id, github_id, author, comment_type, file_path, line_number, created_at, is_bot)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pr_id,
                comment["github_id"],
                comment["author"],
                comment["comment_type"],
                comment["file_path"],
                comment["line_number"],
                comment["created_at"],
                comment["is_bot"],
            ),
        )

    conn.commit()

    print(
        f"Bundle created: {bundle_dir} "
        f"(docs: {doc_counts['comments']} comments, "
        f"{doc_counts['reviews']} reviews, "
        f"{doc_counts['discussion']} discussion)",
        file=sys.stderr,
    )
    return True


def cmd_collect(args: argparse.Namespace) -> int:
    """Handle collect subcommand."""
    base_dir = get_data_dir(args.output)
    conn = get_db(base_dir)
    exclude_bots = not args.include_bots

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
            args.repo, args.pr_number, base_dir, conn, exclude_bots=exclude_bots
        )
        conn.close()
        return 0 if success else 1

    if args.author:
        pr_numbers = list_authored_prs(
            args.repo, args.author, args.limit, args.state, args.since
        )
        if not pr_numbers:
            print(
                f"No PRs found by author {args.author} in {args.repo}", file=sys.stderr
            )
            conn.close()
            return 1

        print(f"Found {len(pr_numbers)} PRs by {args.author}", file=sys.stderr)
        success_count = 0
        skipped_count = 0

        repo_id = get_or_create_repo(conn, args.repo)

        for pr_num in pr_numbers:
            if args.skip_existing and pr_exists(conn, repo_id, pr_num):
                skipped_count += 1
                continue
            if collect_pr(
                args.repo, pr_num, base_dir, conn, "authored", args.author, exclude_bots
            ):
                success_count += 1

        print(
            f"Collected {success_count}/{len(pr_numbers)} PRs "
            f"(skipped {skipped_count} existing)",
            file=sys.stderr,
        )
        conn.close()
        return 0 if success_count > 0 or skipped_count > 0 else 1

    if args.reviewer:
        pr_numbers = list_reviewed_prs(
            args.repo, args.reviewer, args.limit, args.state, args.since
        )
        if not pr_numbers:
            print(f"No PRs reviewed by {args.reviewer} in {args.repo}", file=sys.stderr)
            conn.close()
            return 1

        print(
            f"Found {len(pr_numbers)} PRs reviewed by {args.reviewer}", file=sys.stderr
        )
        success_count = 0
        skipped_count = 0

        repo_id = get_or_create_repo(conn, args.repo)

        for pr_num in pr_numbers:
            if args.skip_existing and pr_exists(conn, repo_id, pr_num):
                # Even if skipping, add reviewer as participant
                pr_id = get_pr_id(conn, repo_id, pr_num)
                if pr_id:
                    add_participant(conn, pr_id, args.reviewer, "reviewer")
                    conn.commit()
                skipped_count += 1
                continue
            if collect_pr(
                args.repo,
                pr_num,
                base_dir,
                conn,
                "reviewed",
                args.reviewer,
                exclude_bots,
            ):
                success_count += 1

        print(
            f"Collected {success_count}/{len(pr_numbers)} PRs "
            f"(skipped {skipped_count} existing)",
            file=sys.stderr,
        )
        conn.close()
        return 0 if success_count > 0 or skipped_count > 0 else 1

    print("Error: Must specify PR number or --author/--reviewer", file=sys.stderr)
    conn.close()
    return 1


def cmd_query(args: argparse.Namespace) -> int:
    """Handle query subcommand - execute SQL query."""
    base_dir = get_data_dir(args.output)
    db_path = get_db_path(base_dir)

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.execute(args.sql)
        rows = cursor.fetchall()

        if not rows:
            print("No results", file=sys.stderr)
            return 0

        # Print header
        columns = [desc[0] for desc in cursor.description]
        print("\t".join(columns))

        # Print rows
        for row in rows:
            print(
                "\t".join(
                    str(row[col]) if row[col] is not None else "" for col in columns
                )
            )

    except sqlite3.Error as e:
        print(f"SQL Error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    return 0


def cmd_db_schema(args: argparse.Namespace) -> int:
    """Show database schema."""
    print(SCHEMA)
    return 0


def cmd_db_migrate(args: argparse.Namespace) -> int:
    """Migrate existing data from old structure to new structure."""
    base_dir = get_data_dir(args.output)
    conn = get_db(base_dir)

    old_authored = base_dir / "authored"
    old_reviewed = base_dir / "reviewed"
    old_prs = base_dir / "prs"

    migrated = 0
    skipped = 0
    errors = 0

    seen_prs: dict[tuple[str, int], Path] = {}  # (repo, pr_num) -> new_path

    def migrate_pr_dir(pr_dir: Path, role: str, user: str) -> bool:
        """Migrate a single PR directory."""
        nonlocal migrated, skipped, errors

        meta_path = pr_dir / "meta.json"
        if not meta_path.exists():
            print(f"  Skipping (no meta.json): {pr_dir}", file=sys.stderr)
            errors += 1
            return False

        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            print(f"  Skipping (invalid meta.json): {pr_dir}", file=sys.stderr)
            errors += 1
            return False

        repo = meta.get("repo", "")
        pr_number = meta.get("pr_number", 0)

        if not repo or not pr_number:
            print(f"  Skipping (missing repo/pr_number): {pr_dir}", file=sys.stderr)
            errors += 1
            return False

        key = (repo, pr_number)

        if key in seen_prs:
            # Already migrated - just add participant and delete duplicate
            repo_id = get_or_create_repo(conn, repo)
            pr_id = get_pr_id(conn, repo_id, pr_number)
            if pr_id:
                participant_role = "author" if role == "authored" else "reviewer"
                add_participant(conn, pr_id, user, participant_role)
                conn.commit()

            # Delete duplicate
            shutil.rmtree(pr_dir)
            print(f"  Merged duplicate: {pr_dir} -> {seen_prs[key]}", file=sys.stderr)
            skipped += 1
            return True

        # New PR - move to new location
        new_path = get_pr_dir(repo, pr_number, base_dir)

        if new_path.exists():
            # Already exists in new location (from previous migration)
            shutil.rmtree(pr_dir)
            seen_prs[key] = new_path
            skipped += 1
            return True

        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pr_dir), str(new_path))
        seen_prs[key] = new_path

        # Insert into database
        repo_id = get_or_create_repo(conn, repo)

        if not pr_exists(conn, repo_id, pr_number):
            pr_author = meta.get("author", "")
            cursor = conn.execute(
                """INSERT INTO prs
                   (repo_id, number, title, author, state, merged, created_at, merged_at,
                    labels, url, file_path, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    repo_id,
                    pr_number,
                    meta.get("title", ""),
                    pr_author,
                    meta.get("state", ""),
                    1 if meta.get("merged") else 0,
                    meta.get("created_at", ""),
                    meta.get("merged_at"),
                    json.dumps(meta.get("labels", [])),
                    meta.get("url", ""),
                    f"{repo.replace('/', '_')}/pr{pr_number}",
                    datetime.now(UTC).isoformat(),
                ),
            )
            pr_id: int = cursor.lastrowid  # type: ignore[assignment]

            # Add author as participant
            if pr_author:
                add_participant(conn, pr_id, pr_author, "author")

            # Add files
            for file_path in meta.get("files", []):
                if isinstance(file_path, str):
                    conn.execute(
                        "INSERT OR IGNORE INTO pr_files (pr_id, file_path) VALUES (?, ?)",
                        (pr_id, file_path),
                    )
                elif isinstance(file_path, dict):
                    conn.execute(
                        """INSERT OR IGNORE INTO pr_files
                           (pr_id, file_path, change_type, additions, deletions)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            pr_id,
                            file_path.get("path", ""),
                            file_path.get("status"),
                            file_path.get("additions", 0),
                            file_path.get("deletions", 0),
                        ),
                    )

            conn.commit()

        # Add role participant
        pr_id = get_pr_id(conn, repo_id, pr_number)
        if pr_id:
            participant_role = "author" if role == "authored" else "reviewer"
            add_participant(conn, pr_id, user, participant_role)
            conn.commit()

        print(f"  Migrated: {pr_dir} -> {new_path}", file=sys.stderr)
        migrated += 1
        return True

    # Migrate authored/
    if old_authored.exists():
        print("Migrating authored/...", file=sys.stderr)
        for user_dir in old_authored.iterdir():
            if not user_dir.is_dir():
                continue
            user = user_dir.name
            for repo_dir in user_dir.iterdir():
                if not repo_dir.is_dir():
                    continue
                for pr_dir in repo_dir.iterdir():
                    if pr_dir.is_dir() and pr_dir.name.startswith("pr"):
                        migrate_pr_dir(pr_dir, "authored", user)

        # Clean up empty directories
        if old_authored.exists():
            shutil.rmtree(old_authored, ignore_errors=True)

    # Migrate reviewed/
    if old_reviewed.exists():
        print("Migrating reviewed/...", file=sys.stderr)
        for user_dir in old_reviewed.iterdir():
            if not user_dir.is_dir():
                continue
            user = user_dir.name
            for repo_dir in user_dir.iterdir():
                if not repo_dir.is_dir():
                    continue
                for pr_dir in repo_dir.iterdir():
                    if pr_dir.is_dir() and pr_dir.name.startswith("pr"):
                        migrate_pr_dir(pr_dir, "reviewed", user)

        if old_reviewed.exists():
            shutil.rmtree(old_reviewed, ignore_errors=True)

    # Migrate prs/ (single PR mode)
    if old_prs.exists():
        print("Migrating prs/...", file=sys.stderr)
        for repo_dir in old_prs.iterdir():
            if not repo_dir.is_dir():
                continue
            for pr_dir in repo_dir.iterdir():
                if pr_dir.is_dir() and pr_dir.name.startswith("pr"):
                    migrate_pr_dir(pr_dir, "single", "")

        if old_prs.exists():
            shutil.rmtree(old_prs, ignore_errors=True)

    conn.close()

    print("\nMigration complete:", file=sys.stderr)
    print(f"  Migrated: {migrated}", file=sys.stderr)
    print(f"  Merged duplicates: {skipped}", file=sys.stderr)
    print(f"  Errors: {errors}", file=sys.stderr)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect GitHub PR data for style analysis and code review",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Data directory (default: ~/.local/share/style-review)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # collect subcommand
    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect PR code and metadata",
    )
    collect_parser.add_argument("repo", help="Repository (owner/repo)")
    collect_parser.add_argument("pr_number", type=int, nargs="?", default=None)
    collect_parser.add_argument("--author", help="Collect PRs authored by user")
    collect_parser.add_argument("--reviewer", help="Collect PRs reviewed by user")
    collect_parser.add_argument("--limit", type=int, default=50)
    collect_parser.add_argument(
        "--state", choices=["all", "open", "closed", "merged"], default="merged"
    )
    collect_parser.add_argument(
        "--since", help="Date filter (2024-01-01 or 1y, 6m, 30d)"
    )
    collect_parser.add_argument("--skip-existing", action="store_true")
    collect_parser.add_argument("--exclude-bots", action="store_true", default=True)
    collect_parser.add_argument("--include-bots", action="store_true")

    # query subcommand
    query_parser = subparsers.add_parser(
        "query",
        help="Execute SQL query on database",
    )
    query_parser.add_argument("sql", help="SQL query to execute")

    # db subcommand
    db_parser = subparsers.add_parser(
        "db",
        help="Database management",
    )
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    db_subparsers.add_parser("schema", help="Show database schema")
    db_subparsers.add_parser("migrate", help="Migrate existing data to new structure")

    args = parser.parse_args()

    if args.command == "collect":
        return cmd_collect(args)
    if args.command == "query":
        return cmd_query(args)
    if args.command == "db":
        if args.db_command == "schema":
            return cmd_db_schema(args)
        if args.db_command == "migrate":
            return cmd_db_migrate(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
