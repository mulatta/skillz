"""Minimal Vikunja REST API client."""

from __future__ import annotations

import json
import mimetypes
import uuid
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path
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
        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": self._auth_header(),
        }
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            self._url(path, query), data=data, headers=headers, method=method.upper()
        )
        raw = self._read(req)
        return _decode_json(raw)

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, query=query)

    def post(
        self, path: str, body: Json = None, query: dict[str, Any] | None = None
    ) -> Any:
        return self.request("POST", path, body, query)

    def put(
        self, path: str, body: Json = None, query: dict[str, Any] | None = None
    ) -> Any:
        return self.request("PUT", path, body, query)

    def delete(self, path: str, query: dict[str, Any] | None = None) -> Any:
        return self.request("DELETE", path, query=query)

    def request_raw(
        self,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        *,
        accept: str = "application/octet-stream",
    ) -> bytes:
        """Send an HTTP request and return the raw response body."""
        req = urllib.request.Request(
            self._url(path, query),
            headers={"Accept": accept, "Authorization": self._auth_header()},
            method=method.upper(),
        )
        return self._read(req)

    def put_multipart_files(
        self, path: str, field_name: str, files: Sequence[Path | str]
    ) -> Any:
        """Upload files as multipart/form-data and decode the JSON response."""
        body, boundary = _encode_multipart_files(field_name, files)
        req = urllib.request.Request(
            self._url(path),
            data=body,
            headers={
                "Accept": "application/json",
                "Authorization": self._auth_header(),
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="PUT",
        )
        return _decode_json(self._read(req))

    def upload_task_attachments(self, task_id: int, files: Sequence[Path | str]) -> Any:
        return self.put_multipart_files(f"/tasks/{task_id}/attachments", "files", files)

    def download_task_attachment(self, task_id: int, attachment_id: int) -> bytes:
        return self.request_raw("GET", f"/tasks/{task_id}/attachments/{attachment_id}")

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

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"
        if not query:
            return url
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
        return url

    def _read(self, req: urllib.request.Request) -> bytes:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw: bytes = resp.read()
                return raw
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode(errors="replace") if exc.fp else ""
            raise APIError(exc.code, _extract_error(body_text)) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError_(str(exc.reason)) from exc

    def _auth_header(self) -> str:
        token = self.api_key.strip()
        if token.lower().startswith("bearer "):
            return token
        return f"Bearer {token}"


def _decode_json(raw: bytes) -> Any:
    if not raw:
        return None
    text = raw.decode()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _encode_multipart_files(
    field_name: str, files: Sequence[Path | str]
) -> tuple[bytes, str]:
    boundary = f"vikunja-cli-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for value in files:
        path = Path(value)
        filename = _quote_multipart(path.name)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{_quote_multipart(field_name)}"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def _quote_multipart(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', r"\"")
        .replace("\r", "_")
        .replace("\n", "_")
    )


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
