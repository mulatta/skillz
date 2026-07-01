"""Human/agent-readable rendering of Nixbot build results.

Output is deliberately plain ``key: value`` blocks separated by blank lines so
an LLM (or ``grep``) can parse it without ANSI/emoji noise. For fully
structured output use ``--json``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Protocol


class ReportBuild(Protocol):
    buildid: int
    status_str: str
    complete: bool
    state_string: str


class ReportAttribute(Protocol):
    build: ReportBuild | None
    attr: str
    error: str | None
    log_url: str | None
    log_tail: str | None
    status_str: str


class ReportEvalBuild(Protocol):
    build: ReportBuild
    attribute_names: Sequence[str]
    attributes: Sequence[ReportAttribute]
    web_url: str


def _kv(key: str, value: object, indent: int = 0) -> None:
    pad = " " * indent
    print(f"{pad}{key}: {value}")


def print_eval_build(ev: ReportEvalBuild) -> None:
    b = ev.build
    print("build:")
    _kv("url", ev.web_url, 2)
    _kv("build_id", b.buildid, 2)
    _kv("status", b.status_str, 2)
    _kv("complete", b.complete, 2)
    _kv("state", b.state_string, 2)

    if not ev.attributes:
        _kv("attributes", f"{len(ev.attribute_names)} (not resolved)", 2)
        return

    counts: Counter[str] = Counter(a.status_str for a in ev.attributes)
    summary = " ".join(f"{k}={n}" for k, n in sorted(counts.items()))
    _kv("attributes", f"{len(ev.attributes)} ({summary})", 2)
    print()

    width = max((len(a.attr) for a in ev.attributes), default=0)
    print("attributes:")
    for a in ev.attributes:
        state = a.build.state_string if a.build else ""
        print(f"  - attr: {a.attr:<{width}}  status: {a.status_str:<9}  state: {state}")


def print_failures(ev: ReportEvalBuild, failures: Sequence[ReportAttribute]) -> None:
    print("build:")
    _kv("url", ev.web_url, 2)
    _kv("status", ev.build.status_str, 2)
    _kv("state", ev.build.state_string, 2)
    _kv("failed_attributes", len(failures), 2)

    for a in failures:
        print()
        print("failure:")
        _kv("attr", a.attr, 2)
        _kv("status", a.status_str, 2)
        if a.build:
            _kv("build_id", a.build.buildid, 2)
            _kv("state", a.build.state_string, 2)
        if a.log_url:
            _kv("log_url", a.log_url, 2)
        if a.error:
            print("  error: |")
            for line in a.error.splitlines():
                print(f"    {line}")
        if a.log_tail:
            print("  log_tail: |")
            for line in a.log_tail.splitlines():
                print(f"    {line}")
