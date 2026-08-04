# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from biorefs_cli.http import HttpClient, HttpResponse, infer_rate_limit_source
from biorefs_cli.rate_limit import (
    API_RATE_LIMIT_POLICIES,
    RateLimiter,
    RateLimitPolicy,
    RateLimitRule,
    get_rate_limit_policy,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class RecordingLimiter(RateLimiter):
    def __init__(self) -> None:
        self.sources: list[str | RateLimitPolicy | None] = []

    def acquire(self, source: str | RateLimitPolicy | None) -> None:
        self.sources.append(source)


class RecordingHttpClient(HttpClient):
    def __init__(self, limiter: RecordingLimiter) -> None:
        super().__init__(timeout_seconds=3, rate_limiter=limiter)
        self.urls: list[str] = []

    def _once(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None,
        headers: dict[str, str],
    ) -> HttpResponse:
        assert headers is not None
        self.urls.append(url)
        return HttpResponse(status=200, headers={}, body=b'{"ok": true}')


class RedirectHttpClient(HttpClient):
    def __init__(self, limiter: RecordingLimiter) -> None:
        super().__init__(timeout_seconds=3, rate_limiter=limiter)
        self.urls: list[str] = []

    def _once(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None,
        headers: dict[str, str],
    ) -> HttpResponse:
        assert headers is not None
        self.urls.append(url)
        if len(self.urls) == 1:
            return HttpResponse(
                status=301,
                headers={"location": "https://pmc.ncbi.nlm.nih.gov/tools/idconv/"},
                body=b"",
            )
        return HttpResponse(status=200, headers={}, body=b'{"ok": true}')


def test_ncbi_without_api_key_uses_three_per_second_policy() -> None:
    ncbi = get_rate_limit_policy("ncbi")

    assert ncbi is not None
    assert get_rate_limit_policy("pubmed") == ncbi
    assert get_rate_limit_policy("pmc") == ncbi
    assert get_rate_limit_policy("pmc-id-converter") == ncbi
    assert ncbi.rules[0].max_requests == 3


def test_ncbi_with_api_key_uses_ten_per_second_policy() -> None:
    ncbi_key = get_rate_limit_policy("ncbi-key")

    assert ncbi_key is not None
    assert get_rate_limit_policy("pubmed-key") == ncbi_key
    assert get_rate_limit_policy("pmc-key") == ncbi_key
    assert get_rate_limit_policy("pmc-id-converter-key") == ncbi_key
    assert ncbi_key.rules[0].max_requests == 10


def test_pubchem_policy_has_second_and_minute_limits() -> None:
    pubchem = API_RATE_LIMIT_POLICIES["pubchem"]

    assert {rule.name for rule in pubchem.rules} == {"per-second", "per-minute"}
    assert any(
        rule.max_requests == 5 and rule.period_seconds == 1.0 for rule in pubchem.rules
    )
    assert any(
        rule.max_requests == 400 and rule.period_seconds == 60.0
        for rule in pubchem.rules
    )


def test_rate_limiter_waits_for_rolling_window() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock.monotonic, sleep=clock.sleep)
    policy = RateLimitPolicy(name="test", rules=(RateLimitRule("per-second", 2, 1.0),))

    limiter.acquire(policy)
    limiter.acquire(policy)
    limiter.acquire(policy)

    assert clock.sleeps == [1.0]


def test_rate_limiter_applies_most_restrictive_rule() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock.monotonic, sleep=clock.sleep)
    policy = RateLimitPolicy(
        name="test",
        rules=(
            RateLimitRule("per-second", 100, 1.0),
            RateLimitRule("per-ten-seconds", 3, 10.0),
        ),
    )

    for _item in range(4):
        limiter.acquire(policy)

    assert clock.sleeps == [10.0]


def test_http_client_infers_source_and_acquires_limit() -> None:
    limiter = RecordingLimiter()
    client = RecordingHttpClient(limiter)

    response = client.get("https://api.openalex.org/works/W1")

    assert response.status == 200
    assert limiter.sources == ["openalex"]


def test_http_client_allows_explicit_rate_limit_source() -> None:
    limiter = RecordingLimiter()
    client = RecordingHttpClient(limiter)

    response = client.get_json(
        "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
        rate_limit_source="pmc",
    )

    assert response == {"ok": True}
    assert limiter.sources == ["pmc"]


def test_http_client_follows_redirects_and_rechecks_rate_source() -> None:
    limiter = RecordingLimiter()
    client = RedirectHttpClient(limiter)

    response = client.get_json("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/")

    assert response == {"ok": True}
    assert client.urls == [
        "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
        "https://pmc.ncbi.nlm.nih.gov/tools/idconv/",
    ]
    assert limiter.sources == ["ncbi", "ncbi"]


def test_infer_rate_limit_source_for_supported_hosts() -> None:
    assert (
        infer_rate_limit_source(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        )
        == "ncbi"
    )
    assert (
        infer_rate_limit_source("https://pmc.ncbi.nlm.nih.gov/tools/idconv/") == "ncbi"
    )
    assert (
        infer_rate_limit_source(
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/aspirin/cids/JSON",
        )
        == "pubchem"
    )
    assert (
        infer_rate_limit_source("https://api.crossref.org/works/10.1/example")
        == "crossref"
    )
    assert (
        infer_rate_limit_source(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        )
        == "europepmc"
    )
    assert (
        infer_rate_limit_source("https://api.semanticscholar.org/graph/v1/paper/123")
        == "semantic-scholar"
    )
    assert (
        infer_rate_limit_source("https://api.biorxiv.org/details/biorxiv/2020-01-01")
        == "biorxiv"
    )
    assert (
        infer_rate_limit_source("https://api.unpaywall.org/v2/10.1/example")
        == "unpaywall"
    )
    assert infer_rate_limit_source("https://example.org/") is None
