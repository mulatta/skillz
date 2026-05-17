"""Small Linkwarden API client."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, cast

from linkwarden_cli.errors import APIError, ConnectionError_

Json = dict[str, Any] | list[Any] | str | int | float | bool | None


class Client:
    """Linkwarden API client using stdlib urllib."""

    def __init__(self, base_url: str, token: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        body: Json = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        data = None
        headers = {"Accept": "application/json", "Authorization": self._auth_header()}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self._url(path, query), data=data, headers=headers, method=method.upper()
        )
        raw = self._read(req)
        return decode_json(raw)

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, query=query)

    def post(self, path: str, body: Json = None, query: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, body, query)

    def put(self, path: str, body: Json = None, query: dict[str, Any] | None = None) -> Any:
        return self.request("PUT", path, body, query)

    def patch(self, path: str, body: Json = None, query: dict[str, Any] | None = None) -> Any:
        return self.request("PATCH", path, body, query)

    def delete(
        self,
        path: str,
        body: Json = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        return self.request("DELETE", path, body, query)

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self.base_url}{path}"
        pairs: list[tuple[str, str]] = []
        for key, value in (query or {}).items():
            if value is None:
                continue
            if isinstance(value, bool):
                pairs.append((key, "true" if value else "false"))
            else:
                pairs.append((key, str(value)))
        if pairs:
            url = f"{url}?{urllib.parse.urlencode(pairs)}"
        return url

    def _read(self, req: urllib.request.Request) -> bytes:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return cast(bytes, resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace") if exc.fp else ""
            raise APIError(exc.code, extract_error(body)) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError_(str(exc.reason)) from exc

    def _auth_header(self) -> str:
        token = self.token.strip()
        return token if token.lower().startswith("bearer ") else f"Bearer {token}"


def decode_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode())
    except json.JSONDecodeError:
        return raw.decode(errors="replace")


def extract_error(body: str) -> str:
    if not body:
        return ""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body
    if isinstance(data, dict):
        for key in ("response", "message", "error"):
            value = data.get(key)
            if isinstance(value, str):
                return value
        return json.dumps(data, ensure_ascii=False)
    return str(data)
