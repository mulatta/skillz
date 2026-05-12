"""Minimal Vikunja REST API client."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from vikunja_cli.errors import APIError, ConnectionError_

Json = dict[str, Any] | list[Any] | str | int | float | bool | None


class Client:
    """Vikunja API client using stdlib urllib."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30) -> None:
        url = base_url.rstrip("/")
        if not url.endswith("/api/v1"):
            url += "/api/v1"
        self.base_url = url
        self.api_key = api_key
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        body: Json = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        """Send an HTTP request and decode JSON responses."""
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"
        if query:
            pairs: list[tuple[str, str]] = []
            for key, value in query.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    pairs.extend((key, str(item)) for item in value)
                else:
                    pairs.append((key, str(value)))
            if pairs:
                url += "?" + urllib.parse.urlencode(pairs)

        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": self._auth_header(),
        }
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode() if exc.fp else ""
            raise APIError(exc.code, _extract_error(body_text)) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError_(str(exc.reason)) from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, query=query)

    def post(self, path: str, body: Json = None, query: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, body, query)

    def put(self, path: str, body: Json = None, query: dict[str, Any] | None = None) -> Any:
        return self.request("PUT", path, body, query)

    def delete(self, path: str, query: dict[str, Any] | None = None) -> Any:
        return self.request("DELETE", path, query=query)

    def paginate(
        self,
        path: str,
        query: dict[str, Any] | None = None,
        *,
        per_page: int = 50,
        max_pages: int = 100,
    ) -> list[Any]:
        """Fetch paginated list endpoints until an empty or short page."""
        result: list[Any] = []
        base_query = dict(query or {})
        for page in range(1, max_pages + 1):
            page_query = {**base_query, "page": page, "per_page": per_page}
            data = self.get(path, page_query)
            if not isinstance(data, list):
                return result
            result.extend(data)
            if len(data) < per_page:
                break
        return result

    def _auth_header(self) -> str:
        token = self.api_key.strip()
        if token.lower().startswith("bearer "):
            return token
        return f"Bearer {token}"


def _extract_error(body_text: str) -> str:
    if not body_text:
        return ""
    try:
        parsed = json.loads(body_text)
    except json.JSONDecodeError:
        return body_text
    if isinstance(parsed, dict):
        for key in ("message", "error", "detail"):
            value = parsed.get(key)
            if isinstance(value, str):
                return value
    return body_text
