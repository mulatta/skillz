"""Thin client for the nixbot JSON API (stdlib urllib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .exceptions import NixbotAPIError


BAD_STATUSES = {
    "failed",
    "failed_eval",
    "dependency_failed",
    "cached_failure",
    "cancelled",
}
RUNNING_STATUSES = {"pending", "evaluating", "building"}


@dataclass(frozen=True)
class NixbotStatus:
    name: str

    @property
    def is_bad(self) -> bool:
        return self.name in BAD_STATUSES


def _status_name(status: str) -> str:
    return status.upper()


@dataclass
class NixbotBuild:
    id: int
    number: int
    status_name: str
    branch: str
    commit_sha: str
    error: str | None = None

    @property
    def buildid(self) -> int:
        return self.id

    @property
    def status(self) -> NixbotStatus:
        return NixbotStatus(self.status_name)

    @property
    def status_str(self) -> str:
        return _status_name(self.status_name)

    @property
    def state_string(self) -> str:
        return self.status_name

    @property
    def complete(self) -> bool:
        return self.status_name not in RUNNING_STATUSES

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> NixbotBuild:
        return cls(
            id=int(d["id"]),
            number=int(d["number"]),
            status_name=str(d["status"]),
            branch=str(d.get("branch") or ""),
            commit_sha=str(d.get("commit_sha") or ""),
            error=d.get("error"),
        )


@dataclass
class NixbotAttribute:
    build: NixbotBuild | None
    attr: str
    error: str | None
    status_name: str
    cached: bool = False
    log_url: str | None = None
    log_tail: str | None = None

    @property
    def status(self) -> NixbotStatus:
        return NixbotStatus(self.status_name)

    @property
    def status_str(self) -> str:
        return _status_name(self.status_name)

    def to_json(self) -> dict[str, Any]:
        return {
            "build_id": self.build.buildid if self.build else None,
            "status": self.status_str,
            "state_string": self.status_name,
            "attr": self.attr,
            "cached": self.cached,
            "error": self.error,
            "log_url": self.log_url,
            "log_tail": self.log_tail,
        }


@dataclass
class NixbotEvalBuild:
    base_url: str
    forge: str
    owner: str
    repo: str
    build: NixbotBuild
    attribute_names: list[str]
    attributes: list[NixbotAttribute] = field(default_factory=list)

    @property
    def web_url(self) -> str:
        return f"{self.base_url}/repos/{self.forge}/{self.owner}/{self.repo}/builds/{self.build.number}"

    def to_json(self) -> dict[str, Any]:
        return {
            "url": self.web_url,
            "build_id": self.build.buildid,
            "number": self.build.number,
            "status": self.build.status_str,
            "state_string": self.build.state_string,
            "complete": self.build.complete,
            "attributes": [a.to_json() for a in self.attributes],
        }


class NixbotClient:
    def __init__(self, base_url: str, forge: str, owner: str, repo: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.forge = forge
        self.owner = owner
        self.repo = repo
        self._last_attributes: list[dict[str, Any]] = []
        self._build_number = 0

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}/api/{path.lstrip('/')}"
        try:
            with urllib.request.urlopen(url) as resp:  # noqa: S310
                body = resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            msg = f"Nixbot request failed: {url}: {e}"
            raise NixbotAPIError(msg) from e
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            msg = f"Nixbot returned invalid JSON: {url}: {e}"
            raise NixbotAPIError(msg) from e

    def raw_log_url(self, build_number: int, attr: str, tail: int | None = None) -> str:
        quoted = urllib.parse.quote(attr, safe="/")
        url = f"{self.base_url}/repos/{self.forge}/{self.owner}/{self.repo}/builds/{build_number}/logs/raw/{quoted}"
        if tail is not None:
            url = f"{url}?{urllib.parse.urlencode({'tail': tail})}"
        return url

    def get_build_by_number(self, number: int) -> NixbotBuild:
        detail = self._get(
            f"repos/{self.forge}/{self.owner}/{self.repo}/builds/{number}"
        )
        self._last_attributes = list(detail.get("attributes") or [])
        self._build_number = number
        return NixbotBuild.from_json(detail["build"])

    def load_eval_build(self, build: NixbotBuild) -> NixbotEvalBuild:
        if not self._last_attributes:
            self.get_build_by_number(build.number)
        return NixbotEvalBuild(
            base_url=self.base_url,
            forge=self.forge,
            owner=self.owner,
            repo=self.repo,
            build=build,
            attribute_names=[str(a.get("attr") or "") for a in self._last_attributes],
        )

    def resolve_attributes(self, names: list[str]) -> list[NixbotAttribute]:
        del names
        return [self._attribute(a) for a in self._last_attributes]

    def _attribute(self, attr: dict[str, Any]) -> NixbotAttribute:
        name = str(attr.get("attr") or "")
        build = NixbotBuild(
            id=int(attr.get("build_id") or 0),
            number=self._build_number,
            status_name=str(attr.get("status") or "pending"),
            branch="",
            commit_sha="",
            error=attr.get("error"),
        )
        return NixbotAttribute(
            build=build,
            attr=name,
            error=attr.get("error"),
            status_name=str(attr.get("status") or "pending"),
            cached=bool(attr.get("cached")),
        )

    def attach_failure_log(self, attribute: NixbotAttribute, *, tail: int) -> None:
        if tail <= 0:
            return
        attribute.log_url = self.raw_log_url(self._build_number, attribute.attr)
        url = self.raw_log_url(self._build_number, attribute.attr, tail)
        try:
            with urllib.request.urlopen(url) as resp:  # noqa: S310
                attribute.log_tail = resp.read().decode(errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            attribute.log_tail = f"<failed to fetch log: {e}>"
