# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Small Miniflux API client."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class MinifluxError(RuntimeError):
    """Miniflux request failed."""


@dataclass(frozen=True)
class MinifluxClient:
    api_url: str
    token: str

    def request(self, path: str, query: dict[str, object] | None = None) -> Any:
        encoded_query = ""
        if query:
            clean = {k: _query_value(v) for k, v in query.items() if v is not None}
            encoded_query = urllib.parse.urlencode(clean)
        url = f"{self.api_url}{path}"
        if encoded_query:
            url = f"{url}?{encoded_query}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Auth-Token": self.token,
                "User-Agent": "miniflux-cli/0.1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            msg = f"Miniflux HTTP {exc.code} for {path}: {error_body}"
            raise MinifluxError(msg) from exc
        except urllib.error.URLError as exc:
            msg = f"Miniflux connection error for {path}: {exc.reason}"
            raise MinifluxError(msg) from exc
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            msg = f"Miniflux returned invalid JSON for {path}"
            raise MinifluxError(msg) from exc

    def categories(self) -> list[dict[str, Any]]:
        data = self.request("/v1/categories")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []

    def feeds(self) -> list[dict[str, Any]]:
        data = self.request("/v1/feeds")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []

    def entries(self, query: dict[str, object]) -> dict[str, Any]:
        data = self.request("/v1/entries", query)
        if isinstance(data, dict):
            return data
        return {"entries": []}

    def entry(self, entry_id: int) -> dict[str, Any]:
        data = self.request(f"/v1/entries/{entry_id}")
        if not isinstance(data, dict):
            msg = f"entry not found: {entry_id}"
            raise MinifluxError(msg)
        return data


def _query_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def resolve_category_id(client: MinifluxClient, value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    wanted = value.casefold()
    for category in client.categories():
        title = category.get("title")
        category_id = category.get("id")
        if (
            isinstance(title, str)
            and title.casefold() == wanted
            and isinstance(category_id, int)
        ):
            return category_id
    msg = f"category not found: {value}"
    raise MinifluxError(msg)
