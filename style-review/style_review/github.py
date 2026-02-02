"""GitHub API utilities for style-review."""

from __future__ import annotations

import base64
import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any


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
