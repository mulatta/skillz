"""style-review: Collect GitHub PR data for style analysis and code review."""

from .cli import main
from .collector import collect_pr, save_docs
from .config import get_data_dir, get_db_path, get_files_dir, get_pr_dir
from .db import SCHEMA, get_db
from .github import gh_api, gh_api_paginate, list_authored_prs, list_reviewed_prs

__all__ = [
    "SCHEMA",
    "collect_pr",
    "get_data_dir",
    "get_db",
    "get_db_path",
    "get_files_dir",
    "get_pr_dir",
    "gh_api",
    "gh_api_paginate",
    "list_authored_prs",
    "list_reviewed_prs",
    "main",
    "save_docs",
]
