"""Database migration utilities for style-review."""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import get_pr_dir
from .db import add_participant, get_or_create_repo, get_pr_id, pr_exists


@dataclass
class MigrationState:
    """State tracking for migration process."""

    migrated: int = 0
    skipped: int = 0
    errors: int = 0
    seen_prs: dict[tuple[str, int], Path] = field(default_factory=dict)


def _read_pr_meta(pr_dir: Path) -> dict[str, Any] | None:
    """Read and validate PR metadata from directory."""
    meta_path = pr_dir / "meta.json"
    if not meta_path.exists():
        print(f"  Skipping (no meta.json): {pr_dir}", file=sys.stderr)
        return None

    try:
        meta: dict[str, Any] = json.loads(meta_path.read_text())
    except json.JSONDecodeError:
        print(f"  Skipping (invalid meta.json): {pr_dir}", file=sys.stderr)
        return None

    if not meta.get("repo") or not meta.get("pr_number"):
        print(f"  Skipping (missing repo/pr_number): {pr_dir}", file=sys.stderr)
        return None

    return meta


def _merge_duplicate(
    conn: sqlite3.Connection,
    pr_dir: Path,
    repo: str,
    pr_number: int,
    existing_path: Path,
    role: str,
    user: str,
) -> None:
    """Merge duplicate PR directory into existing one."""
    repo_id = get_or_create_repo(conn, repo)
    pr_id = get_pr_id(conn, repo_id, pr_number)
    if pr_id:
        participant_role = "author" if role == "authored" else "reviewer"
        add_participant(conn, pr_id, user, participant_role)
        conn.commit()

    shutil.rmtree(pr_dir)
    print(f"  Merged duplicate: {pr_dir} -> {existing_path}", file=sys.stderr)


def _insert_migrated_pr(
    conn: sqlite3.Connection,
    meta: dict[str, Any],
    repo: str,
    pr_number: int,
) -> int | None:
    """Insert migrated PR into database. Returns new PR ID or None."""
    repo_id = get_or_create_repo(conn, repo)

    if pr_exists(conn, repo_id, pr_number):
        return get_pr_id(conn, repo_id, pr_number)

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
    new_pr_id = cursor.lastrowid
    assert new_pr_id is not None

    if pr_author:
        add_participant(conn, new_pr_id, pr_author, "author")

    _insert_pr_files(conn, new_pr_id, meta.get("files", []))
    conn.commit()

    return new_pr_id


def _insert_pr_files(
    conn: sqlite3.Connection,
    pr_id: int,
    files: list[str | dict[str, Any]],
) -> None:
    """Insert PR files into database."""
    for file_path in files:
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


def migrate_pr_dir(
    conn: sqlite3.Connection,
    base_dir: Path,
    pr_dir: Path,
    role: str,
    user: str,
    state: MigrationState,
) -> bool:
    """Migrate a single PR directory."""
    meta = _read_pr_meta(pr_dir)
    if meta is None:
        state.errors += 1
        return False

    repo = meta["repo"]
    pr_number = meta["pr_number"]
    key = (repo, pr_number)

    # Check for duplicate
    if key in state.seen_prs:
        _merge_duplicate(conn, pr_dir, repo, pr_number, state.seen_prs[key], role, user)
        state.skipped += 1
        return True

    new_path = get_pr_dir(repo, pr_number, base_dir)

    # Already exists in new location
    if new_path.exists():
        shutil.rmtree(pr_dir)
        state.seen_prs[key] = new_path
        state.skipped += 1
        return True

    # Move to new location
    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pr_dir), str(new_path))
    state.seen_prs[key] = new_path

    # Insert into database
    pr_id = _insert_migrated_pr(conn, meta, repo, pr_number)

    # Add role participant
    if pr_id:
        participant_role = "author" if role == "authored" else "reviewer"
        add_participant(conn, pr_id, user, participant_role)
        conn.commit()

    print(f"  Migrated: {pr_dir} -> {new_path}", file=sys.stderr)
    state.migrated += 1
    return True


def migrate_directory(
    conn: sqlite3.Connection,
    base_dir: Path,
    old_dir: Path,
    role: str,
    state: MigrationState,
) -> None:
    """Migrate all PRs in a directory structure."""
    if not old_dir.exists():
        return

    print(f"Migrating {old_dir.name}/...", file=sys.stderr)

    for user_dir in old_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user = user_dir.name

        for repo_dir in user_dir.iterdir():
            if not repo_dir.is_dir():
                continue

            for pr_dir in repo_dir.iterdir():
                if pr_dir.is_dir() and pr_dir.name.startswith("pr"):
                    migrate_pr_dir(conn, base_dir, pr_dir, role, user, state)

    shutil.rmtree(old_dir, ignore_errors=True)


def migrate_prs_directory(
    conn: sqlite3.Connection,
    base_dir: Path,
    old_prs: Path,
    state: MigrationState,
) -> None:
    """Migrate old prs/ directory (single PR mode)."""
    if not old_prs.exists():
        return

    print("Migrating prs/...", file=sys.stderr)

    for repo_dir in old_prs.iterdir():
        if not repo_dir.is_dir():
            continue

        for pr_dir in repo_dir.iterdir():
            if pr_dir.is_dir() and pr_dir.name.startswith("pr"):
                migrate_pr_dir(conn, base_dir, pr_dir, "single", "", state)

    shutil.rmtree(old_prs, ignore_errors=True)
