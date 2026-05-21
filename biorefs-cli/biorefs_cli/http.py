"""Small stdlib HTTP helper skeleton."""

from __future__ import annotations

import http.client
import json
import secrets
import time
from dataclasses import dataclass
from typing import cast
from urllib.parse import urljoin, urlparse

from biorefs_cli.errors import HTTPError, RateLimitError
from biorefs_cli.rate_limit import RateLimiter, get_global_rate_limiter

JsonValue = str | int | float | bool | None | dict[str, "JsonValue"] | list["JsonValue"]
JsonObject = dict[str, JsonValue]
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 5


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class HttpClient:
    def __init__(
        self,
        *,
        timeout_seconds: int,
        retry_policy: RetryPolicy | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.retry_policy = retry_policy or RetryPolicy()
        self.rate_limiter = rate_limiter or get_global_rate_limiter()

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> JsonObject:
        response = self.get(
            url,
            headers={"Accept": "application/json", **(headers or {})},
            rate_limit_source=rate_limit_source,
        )
        try:
            decoded = json.loads(response.body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            msg = "remote service returned invalid JSON"
            raise HTTPError(msg, status=response.status) from exc
        if not isinstance(decoded, dict):
            msg = "remote service returned non-object JSON"
            raise HTTPError(msg, status=response.status)
        return cast("JsonObject", decoded)

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        rate_limit_source: str | None = None,
    ) -> HttpResponse:
        last_error: HTTPError | None = None
        for attempt in range(self.retry_policy.attempts):
            try:
                response = self._get_with_redirects(
                    url,
                    headers=headers or {},
                    rate_limit_source=rate_limit_source,
                )
            except OSError:
                last_error = HTTPError("network request failed")
                self._sleep(attempt, None)
                continue
            if response.status == 429:
                retry_after = parse_retry_after(response.headers.get("retry-after"))
                last_error = RateLimitError(retry_after_seconds=retry_after)
                self._sleep(attempt, retry_after)
                continue
            if response.status in self.retry_policy.retry_statuses:
                last_error = HTTPError(
                    "remote service returned transient error", status=response.status
                )
                self._sleep(attempt, None)
                continue
            if response.status >= 400:
                msg = f"remote service returned HTTP {response.status}"
                raise HTTPError(msg, status=response.status)
            return response
        if last_error is not None:
            raise last_error
        msg = "network request failed"
        raise HTTPError(msg)

    def _get_with_redirects(
        self,
        url: str,
        *,
        headers: dict[str, str],
        rate_limit_source: str | None,
    ) -> HttpResponse:
        current_url = url
        for _redirect in range(MAX_REDIRECTS + 1):
            self.rate_limiter.acquire(
                rate_limit_source or infer_rate_limit_source(current_url)
            )
            response = self._get_once(current_url, headers=headers)
            if response.status not in REDIRECT_STATUSES:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            current_url = urljoin(current_url, location)
        msg = "too many redirects"
        raise HTTPError(msg)

    def _get_once(self, url: str, *, headers: dict[str, str]) -> HttpResponse:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname is None:
            msg = "URL must use https"
            raise HTTPError(msg)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        connection = http.client.HTTPSConnection(
            parsed.hostname, timeout=self.timeout_seconds
        )
        try:
            connection.request("GET", target, headers=headers)
            response = connection.getresponse()
            raw_headers = {key.lower(): value for key, value in response.getheaders()}
            return HttpResponse(
                status=response.status, headers=raw_headers, body=response.read()
            )
        finally:
            connection.close()

    def _sleep(self, attempt: int, retry_after_seconds: float | None) -> None:
        if attempt >= self.retry_policy.attempts - 1:
            return
        if retry_after_seconds is not None:
            time.sleep(min(retry_after_seconds, self.retry_policy.max_delay_seconds))
            return
        jitter = self.retry_policy.base_delay_seconds * (secrets.randbelow(1000) / 1000)
        delay = min(
            self.retry_policy.max_delay_seconds,
            (self.retry_policy.base_delay_seconds * (2**attempt)) + jitter,
        )
        time.sleep(delay)


def parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


HOST_RATE_LIMIT_SOURCES = {
    "api.biorxiv.org": "biorxiv",
    "api.crossref.org": "crossref",
    "api.openalex.org": "openalex",
    "api.semanticscholar.org": "semantic-scholar",
    "api.unpaywall.org": "unpaywall",
    "eutils.ncbi.nlm.nih.gov": "ncbi",
    "pmc.ncbi.nlm.nih.gov": "ncbi",
    "pubchem.ncbi.nlm.nih.gov": "pubchem",
    "www.ebi.ac.uk": "europepmc",
    "www.ncbi.nlm.nih.gov": "ncbi",
}


def infer_rate_limit_source(url: str) -> str | None:
    hostname = urlparse(url).hostname
    if hostname is None:
        return None
    return HOST_RATE_LIMIT_SOURCES.get(hostname.lower())
