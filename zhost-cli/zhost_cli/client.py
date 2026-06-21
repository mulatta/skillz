"""zhost (Zotero sync) API client over stdlib urllib.

Implements the subset the agent workflow needs, matching the protocol verified
end-to-end against a live zhost (see the zhost SPEC at the local repo path noted
in README). Key protocol facts encoded here:

- Auth header is `Zotero-API-Key`; every request also sends `Zotero-API-Version`.
- Writes require `If-Unmodified-Since-Version: <current library version>`; the
  server bumps the version and echoes it in `Last-Modified-Version`. A stale
  precondition returns 412 (ConflictError); a missing one returns 428.
- POST and PATCH both *merge* top-level fields (omit = keep, empty = clear);
  the CLI uses POST to create and PATCH to update, but the server treats them
  the same.
- File upload is three steps: authorize (form md5/filename/filesize/mtime with
  `If-None-Match: *` for a new file or `If-Match: <old md5>` to replace) ->
  POST the raw bytes to the returned `/uploads/<token>` URL -> register with
  `upload=<token>`.
- File download returns a 302 to a short-lived presigned S3 URL; the bytes never
  pass back through zhost.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, cast

from zhost_cli.config import API_VERSION
from zhost_cli.errors import APIError, ConflictError, ConnectionError_

Json = dict[str, Any] | list[Any] | str | int | float | bool | None


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return decode_json(self.body)

    def version(self) -> int | None:
        raw = self.headers.get("last-modified-version")
        return int(raw) if raw is not None and raw.isdigit() else None


class Client:
    """zhost API client. Methods map directly onto the Zotero sync endpoints."""

    def __init__(self, base_url: str, api_key: str, user_id: str, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_id = user_id
        self.timeout = timeout

    # -- low-level ---------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        query: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        auth: bool = True,
    ) -> Response:
        headers: dict[str, str] = {}
        if auth:
            headers["Zotero-API-Key"] = self.api_key
            headers["Zotero-API-Version"] = API_VERSION
        if content_type:
            headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(
            self._url(path, query), data=body, headers=headers, method=method.upper()
        )
        return self._send(req)

    def _send(self, req: urllib.request.Request) -> Response:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return Response(resp.status, _lower_headers(resp.headers.items()), resp.read())
        except urllib.error.HTTPError as exc:
            headers = _lower_headers(exc.headers.items() if exc.headers else [])
            body = exc.read() if exc.fp else b""
            message = extract_error(body.decode(errors="replace"))
            if exc.code == 412:
                raw = headers.get("last-modified-version")
                current = int(raw) if raw and raw.isdigit() else None
                raise ConflictError(current, message) from exc
            raise APIError(exc.code, message) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError_(str(exc.reason)) from exc

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self.base_url}{path}"
        pairs: list[tuple[str, str]] = []
        for key, value in (query or {}).items():
            if value is None:
                continue
            # A list value becomes repeated keys (e.g. ?tag=a&tag=b), which the
            # item query reads as separate AND-ed filters.
            for item in value if isinstance(value, list) else [value]:
                pairs.append(
                    (key, "true" if item is True else "false" if item is False else str(item))
                )
        if pairs:
            url = f"{url}?{urllib.parse.urlencode(pairs)}"
        return url

    def user_path(self, suffix: str) -> str:
        return f"/users/{self.user_id}{suffix}"

    # -- sync reads --------------------------------------------------------

    def library_version(self) -> int:
        """Current library version, read from any versions endpoint's header."""
        resp = self.request("GET", self.user_path("/collections"), query={"format": "versions"})
        return resp.version() or 0

    def versions(self, kind: str, since: int = 0) -> dict[str, int]:
        resp = self.request(
            "GET", self.user_path(f"/{kind}s"), query={"format": "versions", "since": since}
        )
        data = resp.json()
        return cast(dict[str, int], data) if isinstance(data, dict) else {}

    def objects(self, kind: str, keys: list[str]) -> list[dict[str, Any]]:
        if not keys:
            return []
        resp = self.request(
            "GET",
            self.user_path(f"/{kind}s"),
            query={f"{kind}Key": ",".join(keys), "format": "json"},
        )
        data = resp.json()
        return cast(list[dict[str, Any]], data) if isinstance(data, list) else []

    def query(self, suffix: str, params: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
        """A single page of a listing: returns the `[{key,version,data}]` array plus
        the Total-Results count. `suffix` selects the endpoint (e.g. "/items",
        "/items/top", "/items/trash", "/collections/<key>/items")."""
        resp = self.request("GET", self.user_path(suffix), query={**params, "format": "json"})
        data = resp.json()
        items = cast(list[dict[str, Any]], data) if isinstance(data, list) else []
        total = resp.headers.get("total-results")
        return items, int(total) if total is not None and total.isdigit() else None

    def query_all(self, suffix: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Every row of a listing, following the Total-Results pagination. The
        server caps a page at 100, so a full dump must walk `start`."""
        page = 100
        out: list[dict[str, Any]] = []
        start = 0
        while True:
            rows, total = self.query(suffix, {**(params or {}), "start": start, "limit": page})
            out.extend(rows)
            start += len(rows)
            if not rows or (total is not None and start >= total) or len(rows) < page:
                return out

    def fulltext(self, key: str) -> dict[str, Any] | None:
        """An attachment's stored full-text index, or None if it has none (404)."""
        from .errors import APIError

        try:
            resp = self.request("GET", self.user_path(f"/items/{key}/fulltext"))
        except APIError as err:
            if err.status == 404:
                return None
            raise
        data = resp.json()
        return cast(dict[str, Any], data) if isinstance(data, dict) else None

    def put_fulltext(self, key: str, content: dict[str, Any]) -> Response:
        """Restore an attachment's full-text index."""
        return self.request(
            "POST",
            self.user_path(f"/items/{key}/fulltext"),
            body=json.dumps(content).encode(),
            content_type="application/json",
        )

    # -- sync writes -------------------------------------------------------

    def write(
        self,
        kind: str,
        objects: list[dict[str, Any]],
        expected: int | None = None,
        method: str = "POST",
    ) -> Response:
        if expected is None:
            expected = self.library_version()
        return self.request(
            method,
            self.user_path(f"/{kind}s"),
            body=json.dumps(objects).encode(),
            content_type="application/json",
            extra_headers={"If-Unmodified-Since-Version": str(expected)},
        )

    def delete(self, kind: str, keys: list[str], expected: int | None = None) -> Response:
        if expected is None:
            expected = self.library_version()
        return self.request(
            "DELETE",
            self.user_path(f"/{kind}s"),
            query={f"{kind}Key": ",".join(keys)},
            extra_headers={"If-Unmodified-Since-Version": str(expected)},
        )

    # -- file upload (3 steps) --------------------------------------------

    def upload_file(self, attach_key: str, path: str, replace_md5: str | None = None) -> Response:
        """Run the full authorize -> upload -> register sequence for `path`."""
        data = open(path, "rb").read()
        md5 = hashlib.md5(data).hexdigest()
        stat = os.stat(path)
        form = {
            "md5": md5,
            "filename": os.path.basename(path),
            "filesize": str(len(data)),
            "mtime": str(int(stat.st_mtime * 1000)),
        }
        precondition = {"If-Match": replace_md5} if replace_md5 else {"If-None-Match": "*"}
        auth = self.request(
            "POST",
            self.user_path(f"/items/{attach_key}/file"),
            body=urllib.parse.urlencode(form).encode(),
            content_type="application/x-www-form-urlencoded",
            extra_headers=precondition,
        )
        authorized = auth.json()
        if isinstance(authorized, dict) and authorized.get("exists"):
            return auth  # server already has these exact bytes (dedup)
        token = authorized["uploadKey"] if isinstance(authorized, dict) else None
        if not token:
            raise APIError(500, "authorize step returned no uploadKey")
        # bytes go straight to the upload endpoint (a bootstrap path, no auth)
        self.request(
            "POST",
            f"/uploads/{token}",
            body=data,
            content_type="application/octet-stream",
            auth=False,
        )
        return self.request(
            "POST",
            self.user_path(f"/items/{attach_key}/file"),
            body=urllib.parse.urlencode({"upload": token}).encode(),
            content_type="application/x-www-form-urlencoded",
        )

    # -- file download -----------------------------------------------------

    def download_location(self, attach_key: str) -> str:
        """The presigned S3 URL for an attachment (the 302 Location), not followed."""
        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(
            self._url(self.user_path(f"/items/{attach_key}/file")),
            headers={"Zotero-API-Key": self.api_key, "Zotero-API-Version": API_VERSION},
        )
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                location = resp.headers.get("location")
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                location = exc.headers.get("Location") if exc.headers else None
            else:
                raise APIError(exc.code, "file download failed") from exc
        except urllib.error.URLError as exc:
            raise ConnectionError_(str(exc.reason)) from exc
        if not location:
            raise APIError(404, "no presigned location for attachment")
        return str(location)

    def download_file(self, attach_key: str, dest: str) -> int:
        location = self.download_location(attach_key)
        with urllib.request.urlopen(location, timeout=self.timeout) as resp:
            data = resp.read()
        with open(dest, "wb") as out:
            out.write(data)
        return len(data)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _lower_headers(items: Any) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in items}


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
        return body.strip()
    if isinstance(data, dict):
        for key in ("message", "error"):
            value = data.get(key)
            if isinstance(value, str):
                return value
        return json.dumps(data, ensure_ascii=False)
    return str(data)
