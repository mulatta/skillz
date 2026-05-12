"""Resolve human-friendly references to Vikunja numeric IDs."""

from __future__ import annotations

from typing import Any, Protocol

from vikunja_cli.errors import InputError


class API(Protocol):
    def get(self, path: str, query: dict[str, Any] | None = None) -> Any: ...

    def paginate(
        self,
        path: str,
        query: dict[str, Any] | None = None,
        *,
        per_page: int = 50,
        max_pages: int = 100,
    ) -> list[Any]: ...


def is_id(value: str) -> bool:
    return value.isdecimal()


def project_id(client: API, ref: str) -> int:
    if is_id(ref):
        return int(ref)
    matches = _exact_matches(
        client.paginate("/projects", {"s": ref, "is_archived": "true"}),
        "title",
        ref,
    )
    return _single_id("project", ref, matches)


def task_id(client: API, ref: str) -> int:
    if is_id(ref):
        return int(ref)
    tasks = client.get("/tasks", {"s": ref, "per_page": 50})
    if not isinstance(tasks, list):
        raise InputError(f"could not resolve task {ref!r}")
    matches = [task for task in tasks if task.get("identifier") == ref]
    return _single_id("task", ref, matches)


def label_id(client: API, ref: str) -> int:
    if is_id(ref):
        return int(ref)
    matches = _exact_matches(client.paginate("/labels", {"s": ref}), "title", ref)
    return _single_id("label", ref, matches)


def view_id(client: API, project: int, ref: str) -> int:
    if is_id(ref):
        return int(ref)
    views = client.get(f"/projects/{project}/views")
    if not isinstance(views, list):
        raise InputError(f"could not resolve view {ref!r}")
    matches = _exact_matches(views, "title", ref)
    return _single_id("view", ref, matches)


def bucket_id(client: API, project: int, view: int, ref: str) -> int:
    if is_id(ref):
        return int(ref)
    buckets = client.get(f"/projects/{project}/views/{view}/buckets")
    if not isinstance(buckets, list):
        raise InputError(f"could not resolve bucket {ref!r}")
    matches = _exact_matches(buckets, "title", ref)
    return _single_id("bucket", ref, matches)


def _exact_matches(items: list[Any], key: str, value: str) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict) and item.get(key) == value]


def _single_id(kind: str, ref: str, matches: list[dict[str, Any]]) -> int:
    if not matches:
        raise InputError(f"no {kind} exactly matches {ref!r}")
    if len(matches) > 1:
        choices = ", ".join(
            f"{item.get('id')}:{item.get('title', item.get('identifier', '?'))}" for item in matches
        )
        raise InputError(f"ambiguous {kind} {ref!r}; candidates: {choices}")
    value = matches[0].get("id")
    if not isinstance(value, int):
        raise InputError(f"resolved {kind} {ref!r} has no numeric id")
    return value
