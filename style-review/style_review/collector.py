"""PR data collection for style-review."""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import get_file_extension, get_pr_dir
from .db import add_participant, get_or_create_repo, get_pr_id
from .github import get_file_at_ref, gh_api, gh_api_paginate, is_bot


@dataclass
class CollectedRecords:
    """Records collected from PR for database insertion."""

    files: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)


def _save_summary(docs_dir: Path, pr_data: dict[str, Any]) -> None:
    """Save PR summary (body)."""
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


def _collect_line_comments(
    comments_dir: Path,
    repo: str,
    pr_number: int,
    exclude_bots: bool,
) -> tuple[int, list[dict[str, Any]]]:
    """Collect and save line comments. Returns count and records."""
    count = 0
    records: list[dict[str, Any]] = []

    for comment in gh_api_paginate(f"/repos/{repo}/pulls/{pr_number}/comments"):
        user = comment.get("user") or {}
        user_is_bot = is_bot(user)
        if exclude_bots and user_is_bot:
            continue

        comment_id = comment.get("id", 0)
        commenter = user.get("login", "unknown") if user else "unknown"
        path = comment.get("path", "")
        line = comment.get("line") or comment.get("original_line") or 0
        created_at = comment.get("created_at", "")

        content = f"""# Comment by {commenter}

File: `{path}` | Line: {line} | Side: {comment.get("side", "RIGHT")}

## Code Context

```{get_file_extension(path)}
{comment.get("diff_hunk", "")}
```

## Feedback

{comment.get("body", "")}
"""
        (comments_dir / f"comment-{comment_id}.md").write_text(content)
        count += 1

        records.append(
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

    return count, records


def _collect_reviews(
    reviews_dir: Path,
    repo: str,
    pr_number: int,
    pr_author: str,
    exclude_bots: bool,
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect and save reviews. Returns count, comment records, review records."""
    count = 0
    comment_records: list[dict[str, Any]] = []
    review_records: list[dict[str, Any]] = []

    for review in gh_api_paginate(f"/repos/{repo}/pulls/{pr_number}/reviews"):
        user = review.get("user") or {}
        user_is_bot = is_bot(user)
        if exclude_bots and user_is_bot:
            continue

        review_id = review.get("id", 0)
        reviewer = user.get("login", "unknown") if user else "unknown"
        state = review.get("state", "")
        body = review.get("body") or ""
        submitted_at = review.get("submitted_at", "")

        review_records.append(
            {
                "github_id": review_id,
                "reviewer": reviewer,
                "pr_author": pr_author,
                "state": state,
                "submitted_at": submitted_at,
            }
        )

        if not body and state == "APPROVED":
            continue

        content = f"""# Review by {reviewer}

State: {state}
Submitted: {submitted_at}

## Summary

{body if body else "(No summary provided)"}
"""
        (reviews_dir / f"review-{review_id}.md").write_text(content)
        count += 1

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

    return count, comment_records, review_records


def _collect_discussion(
    discussion_dir: Path,
    repo: str,
    pr_number: int,
    exclude_bots: bool,
) -> tuple[int, list[dict[str, Any]]]:
    """Collect and save discussion comments. Returns count and records."""
    count = 0
    records: list[dict[str, Any]] = []

    for comment in gh_api_paginate(f"/repos/{repo}/issues/{pr_number}/comments"):
        user = comment.get("user") or {}
        user_is_bot = is_bot(user)
        if exclude_bots and user_is_bot:
            continue

        comment_id = comment.get("id", 0)
        commenter = user.get("login", "unknown") if user else "unknown"
        created_at = comment.get("created_at", "")

        content = f"""# Comment by {commenter}

Date: {created_at}

{comment.get("body", "")}
"""
        (discussion_dir / f"disc-{comment_id}.md").write_text(content)
        count += 1

        records.append(
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

    return count, records


def save_docs(
    bundle_dir: Path,
    pr_data: dict[str, Any],
    repo: str,
    pr_number: int,
    exclude_bots: bool = True,
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch and save documentation. Returns counts, comment records, review records."""
    docs_dir = bundle_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    counts = {"summary": 1, "comments": 0, "reviews": 0, "discussion": 0}
    comment_records: list[dict[str, Any]] = []
    review_records: list[dict[str, Any]] = []
    pr_author = (pr_data.get("user") or {}).get("login", "")

    _save_summary(docs_dir, pr_data)

    comments_dir = docs_dir / "comments"
    comments_dir.mkdir(exist_ok=True)
    counts["comments"], records = _collect_line_comments(
        comments_dir, repo, pr_number, exclude_bots
    )
    comment_records.extend(records)

    reviews_dir = docs_dir / "reviews"
    reviews_dir.mkdir(exist_ok=True)
    counts["reviews"], c_recs, r_recs = _collect_reviews(
        reviews_dir, repo, pr_number, pr_author, exclude_bots
    )
    comment_records.extend(c_recs)
    review_records.extend(r_recs)

    discussion_dir = docs_dir / "discussion"
    discussion_dir.mkdir(exist_ok=True)
    counts["discussion"], records = _collect_discussion(
        discussion_dir, repo, pr_number, exclude_bots
    )
    comment_records.extend(records)

    return counts, comment_records, review_records


def _fetch_files(
    repo: str,
    pr_number: int,
    head_sha: str,
    code_dir: Path,
    diffs_dir: Path,
) -> list[dict[str, Any]]:
    """Fetch changed files and save code/diffs. Returns file records."""
    file_records: list[dict[str, Any]] = []

    for file_info in gh_api_paginate(f"/repos/{repo}/pulls/{pr_number}/files"):
        filename = file_info.get("filename", "")
        if not filename:
            continue

        status = file_info.get("status", "")
        patch = file_info.get("patch", "")
        additions = file_info.get("additions", 0)
        deletions = file_info.get("deletions", 0)

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
            (diffs_dir / f"{safe_name}.patch").write_text(patch)

        if status in ("added", "modified", "renamed", "copied"):
            content = get_file_at_ref(repo, filename, head_sha)
            if content:
                (code_dir / safe_name).write_text(content)
                print(f"  Saved: {filename}", file=sys.stderr)

    return file_records


def _insert_pr_record(
    conn: sqlite3.Connection,
    repo_id: int,
    pr_number: int,
    pr_data: dict[str, Any],
    file_path: str,
) -> int:
    """Insert PR into database and return PR ID."""
    pr_author = (pr_data.get("user") or {}).get("login", "")
    labels = json.dumps([label.get("name", "") for label in pr_data.get("labels", [])])

    cursor = conn.execute(
        """INSERT INTO prs
           (repo_id, number, title, author, state, merged, created_at, merged_at,
            labels, url, file_path, collected_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            repo_id,
            pr_number,
            pr_data.get("title", ""),
            pr_author,
            pr_data.get("state", ""),
            1 if pr_data.get("merged") else 0,
            pr_data.get("created_at", ""),
            pr_data.get("merged_at"),
            labels,
            pr_data.get("html_url", ""),
            file_path,
            datetime.now(UTC).isoformat(),
        ),
    )
    pr_id = cursor.lastrowid
    assert pr_id is not None

    add_participant(conn, pr_id, pr_author, "author")
    return pr_id


def _insert_related_records(
    conn: sqlite3.Connection,
    pr_id: int,
    pr_author: str,
    records: CollectedRecords,
) -> None:
    """Insert files, comments, and reviews for a PR."""
    # Insert files
    for f in records.files:
        conn.execute(
            """INSERT OR IGNORE INTO pr_files
               (pr_id, file_path, change_type, additions, deletions)
               VALUES (?, ?, ?, ?, ?)""",
            (pr_id, f["file_path"], f["change_type"], f["additions"], f["deletions"]),
        )

    # Insert comments and track commenters
    commenters = set()
    for c in records.comments:
        conn.execute(
            """INSERT OR IGNORE INTO comments
               (pr_id, github_id, author, comment_type, file_path, line_number, created_at, is_bot)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pr_id,
                c["github_id"],
                c["author"],
                c["comment_type"],
                c["file_path"],
                c["line_number"],
                c["created_at"],
                c["is_bot"],
            ),
        )
        if c["author"] != pr_author:
            commenters.add(c["author"])

    for commenter in commenters:
        add_participant(conn, pr_id, commenter, "commenter")

    # Insert reviews
    for r in records.reviews:
        conn.execute(
            """INSERT OR IGNORE INTO reviews
               (pr_id, github_id, reviewer, pr_author, state, submitted_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                pr_id,
                r["github_id"],
                r["reviewer"],
                r["pr_author"],
                r["state"],
                r["submitted_at"],
            ),
        )
        add_participant(conn, pr_id, r["reviewer"], "reviewer")


def collect_pr(
    repo: str,
    pr_number: int,
    base_dir: Path,
    conn: sqlite3.Connection,
    role: str | None = None,
    user: str | None = None,
    exclude_bots: bool = True,
) -> bool:
    """Collect PR data and create bundle."""
    repo_id = get_or_create_repo(conn, repo)

    existing_pr_id = get_pr_id(conn, repo_id, pr_number)
    if existing_pr_id:
        if role and user:
            add_participant(conn, existing_pr_id, user, role.rstrip("ed"))
            conn.commit()
            print(
                f"PR #{pr_number} already exists, added {user} as {role}",
                file=sys.stderr,
            )
        else:
            print(f"PR #{pr_number} already exists in database", file=sys.stderr)
        return True

    print(f"Fetching PR #{pr_number} from {repo}...", file=sys.stderr)

    pr_data = gh_api(f"/repos/{repo}/pulls/{pr_number}")
    if not isinstance(pr_data, dict):
        print(f"Error: Could not fetch PR #{pr_number}", file=sys.stderr)
        return False

    head_sha = pr_data.get("head", {}).get("sha", "")
    if not head_sha:
        print("Error: Could not determine head SHA", file=sys.stderr)
        return False

    bundle_dir = get_pr_dir(repo, pr_number, base_dir)
    code_dir = bundle_dir / "code"
    diffs_dir = bundle_dir / "diffs"
    code_dir.mkdir(parents=True, exist_ok=True)
    diffs_dir.mkdir(parents=True, exist_ok=True)

    records = CollectedRecords()
    records.files = _fetch_files(repo, pr_number, head_sha, code_dir, diffs_dir)

    doc_counts, comment_records, review_records = save_docs(
        bundle_dir, pr_data, repo, pr_number, exclude_bots
    )
    records.comments = comment_records
    records.reviews = review_records

    # Save metadata JSON
    repo_slug = repo.replace("/", "_")
    file_path = f"{repo_slug}/pr{pr_number}"
    meta = {
        "repo": repo,
        "pr_number": pr_number,
        "title": pr_data.get("title", ""),
        "author": (pr_data.get("user") or {}).get("login", ""),
        "state": pr_data.get("state", ""),
        "merged": pr_data.get("merged", False),
        "base_sha": pr_data.get("base", {}).get("sha", ""),
        "head_sha": head_sha,
        "merge_commit_sha": pr_data.get("merge_commit_sha"),
        "created_at": pr_data.get("created_at", ""),
        "merged_at": pr_data.get("merged_at"),
        "labels": [label.get("name", "") for label in pr_data.get("labels", [])],
        "url": pr_data.get("html_url", ""),
        "files": [f["file_path"] for f in records.files],
        "doc_counts": doc_counts,
    }
    (bundle_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # Insert into database
    pr_id = _insert_pr_record(conn, repo_id, pr_number, pr_data, file_path)
    pr_author = (pr_data.get("user") or {}).get("login", "")

    if role and user:
        participant_role = "author" if role == "authored" else "reviewer"
        add_participant(conn, pr_id, user, participant_role)

    _insert_related_records(conn, pr_id, pr_author, records)
    conn.commit()

    print(
        f"Bundle created: {bundle_dir} "
        f"(docs: {doc_counts['comments']} comments, "
        f"{doc_counts['reviews']} reviews, "
        f"{doc_counts['discussion']} discussion)",
        file=sys.stderr,
    )
    return True
