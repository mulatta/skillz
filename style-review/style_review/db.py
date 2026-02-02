"""Database schema and operations for style-review."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import get_db_path

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

-- Reviews (for cross-validation tracking)
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    pr_id INTEGER NOT NULL REFERENCES prs(id),
    github_id INTEGER NOT NULL,
    reviewer TEXT NOT NULL,
    pr_author TEXT NOT NULL,
    state TEXT NOT NULL,
    submitted_at TEXT,
    UNIQUE(pr_id, github_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_prs_author ON prs(author);
CREATE INDEX IF NOT EXISTS idx_prs_repo ON prs(repo_id);
CREATE INDEX IF NOT EXISTS idx_participants_user ON pr_participants(user);
CREATE INDEX IF NOT EXISTS idx_participants_role ON pr_participants(user, role);
CREATE INDEX IF NOT EXISTS idx_comments_author ON comments(author);
CREATE INDEX IF NOT EXISTS idx_comments_type ON comments(comment_type);
CREATE INDEX IF NOT EXISTS idx_reviews_reviewer ON reviews(reviewer);
CREATE INDEX IF NOT EXISTS idx_reviews_author ON reviews(pr_author);
CREATE INDEX IF NOT EXISTS idx_reviews_pair ON reviews(reviewer, pr_author);
"""


def get_db(base_dir: Path) -> sqlite3.Connection:
    """Get database connection, creating tables if needed."""
    db_path = get_db_path(base_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_or_create_repo(conn: sqlite3.Connection, repo: str) -> int:
    """Get or create repo entry, return repo_id."""
    owner, name = repo.split("/", 1)
    cursor = conn.execute(
        "SELECT id FROM repos WHERE owner = ? AND name = ?",
        (owner, name),
    )
    row = cursor.fetchone()
    if row:
        return int(row["id"])

    cursor = conn.execute(
        "INSERT INTO repos (owner, name) VALUES (?, ?)",
        (owner, name),
    )
    repo_id = cursor.lastrowid
    assert repo_id is not None
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
    return int(row["id"]) if row else None


def add_participant(conn: sqlite3.Connection, pr_id: int, user: str, role: str) -> None:
    """Add participant to PR (idempotent)."""
    conn.execute(
        "INSERT OR IGNORE INTO pr_participants (pr_id, user, role) VALUES (?, ?, ?)",
        (pr_id, user, role),
    )
