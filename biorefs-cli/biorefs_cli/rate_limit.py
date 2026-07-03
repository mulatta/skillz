"""Generic API rate-limit policies and limiter."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    """Maximum requests allowed inside a rolling time window."""

    name: str
    max_requests: int
    period_seconds: float


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Named source policy composed of one or more rolling-window rules."""

    name: str
    rules: tuple[RateLimitRule, ...]


NCBI_NO_KEY_POLICY = RateLimitPolicy(
    name="ncbi",
    rules=(RateLimitRule("per-second", max_requests=3, period_seconds=1.0),),
)
NCBI_KEY_POLICY = RateLimitPolicy(
    name="ncbi-key",
    rules=(RateLimitRule("per-second", max_requests=10, period_seconds=1.0),),
)

API_RATE_LIMIT_POLICIES: dict[str, RateLimitPolicy] = {
    # NCBI allows 3 req/s without an API key and 10 req/s with one. Host
    # inference must use the conservative keyless policy because URLs alone do
    # not prove a usable API key was configured.
    "ncbi": NCBI_NO_KEY_POLICY,
    "pubmed": NCBI_NO_KEY_POLICY,
    "pmc": NCBI_NO_KEY_POLICY,
    "pmc-id-converter": NCBI_NO_KEY_POLICY,
    "ncbi-key": NCBI_KEY_POLICY,
    "pubmed-key": NCBI_KEY_POLICY,
    "pmc-key": NCBI_KEY_POLICY,
    "pmc-id-converter-key": NCBI_KEY_POLICY,
    "openalex": RateLimitPolicy(
        name="openalex",
        rules=(RateLimitRule("per-second", max_requests=10, period_seconds=1.0),),
    ),
    "crossref": RateLimitPolicy(
        name="crossref",
        rules=(RateLimitRule("per-second", max_requests=10, period_seconds=1.0),),
    ),
    "europepmc": RateLimitPolicy(
        name="europepmc",
        rules=(RateLimitRule("per-second", max_requests=10, period_seconds=1.0),),
    ),
    "pubchem": RateLimitPolicy(
        name="pubchem",
        rules=(
            RateLimitRule("per-second", max_requests=5, period_seconds=1.0),
            RateLimitRule("per-minute", max_requests=400, period_seconds=60.0),
        ),
    ),
    "semantic-scholar": RateLimitPolicy(
        name="semantic-scholar",
        rules=(RateLimitRule("per-second", max_requests=10, period_seconds=1.0),),
    ),
    "uniprot": RateLimitPolicy(
        name="uniprot",
        rules=(
            RateLimitRule("per-second", max_requests=5, period_seconds=1.0),
            RateLimitRule("per-minute", max_requests=200, period_seconds=60.0),
        ),
    ),
    "biorxiv": RateLimitPolicy(
        name="biorxiv",
        rules=(RateLimitRule("per-second", max_requests=1, period_seconds=1.0),),
    ),
    "unpaywall": RateLimitPolicy(
        name="unpaywall",
        rules=(RateLimitRule("per-second", max_requests=10, period_seconds=1.0),),
    ),
    "rcsb": RateLimitPolicy(
        name="rcsb",
        rules=(RateLimitRule("per-second", max_requests=10, period_seconds=1.0),),
    ),
    "alphafold": RateLimitPolicy(
        name="alphafold",
        rules=(RateLimitRule("per-second", max_requests=10, period_seconds=1.0),),
    ),
}


class RateLimiter:
    """Thread-safe rolling-window limiter for all supported APIs."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], deque[float]] = {}

    def acquire(self, source: str | RateLimitPolicy | None) -> None:
        policy = get_rate_limit_policy(source)
        if policy is None:
            return
        while True:
            with self._lock:
                wait_seconds = self._reserve_or_wait(policy, self._clock())
            if wait_seconds <= 0:
                return
            self._sleep(wait_seconds)

    def _reserve_or_wait(self, policy: RateLimitPolicy, now: float) -> float:
        waits = [self._wait_for_rule(policy.name, rule, now) for rule in policy.rules]
        wait_seconds = max(waits, default=0.0)
        if wait_seconds > 0:
            return wait_seconds
        for rule in policy.rules:
            self._bucket(policy.name, rule).append(now)
        return 0.0

    def _wait_for_rule(
        self, policy_name: str, rule: RateLimitRule, now: float
    ) -> float:
        bucket = self._bucket(policy_name, rule)
        while bucket and now - bucket[0] >= rule.period_seconds:
            bucket.popleft()
        if len(bucket) < rule.max_requests:
            return 0.0
        oldest = bucket[0]
        return max(0.0, rule.period_seconds - (now - oldest))

    def _bucket(self, policy_name: str, rule: RateLimitRule) -> deque[float]:
        key = (policy_name, rule.name)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = deque()
            self._buckets[key] = bucket
        return bucket


_GLOBAL_RATE_LIMITER = RateLimiter()


def get_global_rate_limiter() -> RateLimiter:
    return _GLOBAL_RATE_LIMITER


def get_rate_limit_policy(
    source: str | RateLimitPolicy | None,
) -> RateLimitPolicy | None:
    if source is None or isinstance(source, RateLimitPolicy):
        return source
    return API_RATE_LIMIT_POLICIES.get(source.lower())
