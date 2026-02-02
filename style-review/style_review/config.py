"""Configuration and path utilities for style-review."""

from __future__ import annotations

import os
from pathlib import Path

# File extension to language mapping for syntax highlighting
EXT_MAP = {
    ".nix": "nix",
    ".py": "python",
    ".rs": "rust",
    ".go": "go",
    ".js": "javascript",
    ".ts": "typescript",
    ".sh": "bash",
    ".md": "markdown",
}


def get_data_dir(custom_path: str | None = None) -> Path:
    """Get the base data directory for style-review."""
    if custom_path:
        return Path(custom_path).expanduser()
    xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg_data) / "style-review"


def get_db_path(base_dir: Path) -> Path:
    """Get the SQLite database path."""
    return base_dir / "style-review.db"


def get_files_dir(base_dir: Path) -> Path:
    """Get the files directory for storing PR content."""
    return base_dir / "files"


def get_pr_dir(repo: str, pr_number: int, base_dir: Path) -> Path:
    """Get the PR directory path.

    New structure: files/<owner_repo>/pr<N>/
    """
    repo_slug = repo.replace("/", "_")
    return get_files_dir(base_dir) / repo_slug / f"pr{pr_number}"


def get_file_extension(path: str) -> str:
    """Get file extension for syntax highlighting."""
    for ext, lang in EXT_MAP.items():
        if path.endswith(ext):
            return lang
    return ""
