"""Command handlers for vikunja-cli."""

from __future__ import annotations

import argparse
from typing import Any, Protocol

from vikunja_cli import resolvers
from vikunja_cli.errors import InputError
from vikunja_cli.output import emit, emit_table, short, ts

DUE_NOTIFICATION_NAMES = {
    "reminder": {"task.reminder"},
    "overdue": {"task.undone.overdue"},
    "due": {"task.reminder", "task.undone.overdue"},
}


class ClientLike(Protocol):
    def get(self, path: str, query: dict[str, Any] | None = None) -> Any: ...

    def post(self, path: str, body: Any = None, query: dict[str, Any] | None = None) -> Any: ...

    def put(self, path: str, body: Any = None, query: dict[str, Any] | None = None) -> Any: ...

    def delete(self, path: str, query: dict[str, Any] | None = None) -> Any: ...

    def paginate(
        self,
        path: str,
        query: dict[str, Any] | None = None,
        *,
        per_page: int = 50,
        max_pages: int = 100,
    ) -> list[Any]: ...


def cmd_project_list(client: ClientLike, ns: argparse.Namespace) -> None:
    query = {"s": ns.search, "is_archived": "true" if ns.archived else None}
    data = client.paginate("/projects", query) if ns.all else client.get("/projects", query)
    emit(data, use_json=ns.use_json, text_fn=_print_projects)


def cmd_project_show(client: ClientLike, ns: argparse.Namespace) -> None:
    pid = resolvers.project_id(client, ns.project)
    data = client.get(f"/projects/{pid}")
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_projects([item]))


def cmd_project_create(client: ClientLike, ns: argparse.Namespace) -> None:
    body = _clean(
        {
            "title": ns.title,
            "description": ns.description,
            "hex_color": ns.color,
            "parent_project_id": resolvers.project_id(client, ns.parent) if ns.parent else None,
        }
    )
    data = client.put("/projects", body)
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_projects([item]))


def cmd_project_update(client: ClientLike, ns: argparse.Namespace) -> None:
    pid = resolvers.project_id(client, ns.project)
    body = _clean(
        {
            "title": ns.title,
            "description": ns.description,
            "hex_color": ns.color,
            "is_archived": ns.is_archived,
        }
    )
    if not body:
        raise InputError("no project fields to update")
    data = client.post(f"/projects/{pid}", body)
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_projects([item]))


def cmd_project_delete(client: ClientLike, ns: argparse.Namespace) -> None:
    _require_yes(ns)
    pid = resolvers.project_id(client, ns.project)
    data = client.delete(f"/projects/{pid}")
    emit(data or {"deleted": pid}, use_json=ns.use_json)


def cmd_task_list(client: ClientLike, ns: argparse.Namespace) -> None:
    query: dict[str, Any] = {
        "s": ns.search,
        "filter": _combine_filter(ns.filter, _project_filter(client, ns.project)),
        "sort_by": ns.sort_by,
        "order_by": ns.order_by,
        "expand": ns.expand,
    }
    data = client.paginate("/tasks", query) if ns.all else client.get("/tasks", query)
    emit(data, use_json=ns.use_json, text_fn=_print_tasks)


def cmd_task_show(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    data = client.get(f"/tasks/{tid}")
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_tasks([item]))


def cmd_task_create(client: ClientLike, ns: argparse.Namespace) -> None:
    pid = resolvers.project_id(client, ns.project)
    body = _clean(
        {
            "title": ns.title,
            "description": ns.description,
            "due_date": ns.due,
            "start_date": ns.start,
            "end_date": ns.end,
            "priority": ns.priority,
            "hex_color": ns.color,
        }
    )
    data = client.put(f"/projects/{pid}/tasks", body)
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_tasks([item]))


def cmd_task_update(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    body = _clean(
        {
            "title": ns.title,
            "description": ns.description,
            "due_date": ns.due,
            "start_date": ns.start,
            "end_date": ns.end,
            "priority": ns.priority,
            "percent_done": ns.percent_done,
            "hex_color": ns.color,
        }
    )
    if not body:
        raise InputError("no task fields to update")
    data = client.post(f"/tasks/{tid}", body)
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_tasks([item]))


def cmd_task_complete(client: ClientLike, ns: argparse.Namespace) -> None:
    _task_done(client, ns, True)


def cmd_task_reopen(client: ClientLike, ns: argparse.Namespace) -> None:
    _task_done(client, ns, False)


def _task_done(client: ClientLike, ns: argparse.Namespace, done: bool) -> None:
    tid = resolvers.task_id(client, ns.task)
    data = client.post(f"/tasks/{tid}", {"done": done})
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_tasks([item]))


def cmd_task_duplicate(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    data = client.put(f"/tasks/{tid}/duplicate")
    emit(data, use_json=ns.use_json)


def cmd_task_delete(client: ClientLike, ns: argparse.Namespace) -> None:
    _require_yes(ns)
    tid = resolvers.task_id(client, ns.task)
    data = client.delete(f"/tasks/{tid}")
    emit(data or {"deleted": tid}, use_json=ns.use_json)


def cmd_label_list(client: ClientLike, ns: argparse.Namespace) -> None:
    data = (
        client.paginate("/labels", {"s": ns.search})
        if ns.all
        else client.get("/labels", {"s": ns.search})
    )
    emit(data, use_json=ns.use_json, text_fn=_print_labels)


def cmd_label_show(client: ClientLike, ns: argparse.Namespace) -> None:
    lid = resolvers.label_id(client, ns.label)
    data = client.get(f"/labels/{lid}")
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_labels([item]))


def cmd_label_create(client: ClientLike, ns: argparse.Namespace) -> None:
    data = client.put(
        "/labels", _clean({"title": ns.title, "description": ns.description, "hex_color": ns.color})
    )
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_labels([item]))


def cmd_label_update(client: ClientLike, ns: argparse.Namespace) -> None:
    lid = resolvers.label_id(client, ns.label)
    body = _clean({"title": ns.title, "description": ns.description, "hex_color": ns.color})
    if not body:
        raise InputError("no label fields to update")
    data = client.put(f"/labels/{lid}", body)
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_labels([item]))


def cmd_label_delete(client: ClientLike, ns: argparse.Namespace) -> None:
    _require_yes(ns)
    lid = resolvers.label_id(client, ns.label)
    data = client.delete(f"/labels/{lid}")
    emit(data or {"deleted": lid}, use_json=ns.use_json)


def cmd_label_add_to_task(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    lid = resolvers.label_id(client, ns.label)
    data = client.put(f"/tasks/{tid}/labels", {"label_id": lid})
    emit(data, use_json=ns.use_json)


def cmd_label_remove_from_task(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    lid = resolvers.label_id(client, ns.label)
    data = client.delete(f"/tasks/{tid}/labels/{lid}")
    emit(data or {"task_id": tid, "removed_label_id": lid}, use_json=ns.use_json)


def cmd_label_replace_on_task(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    labels = [{"id": resolvers.label_id(client, label)} for label in ns.label]
    data = client.post(f"/tasks/{tid}/labels/bulk", {"labels": labels})
    emit(data, use_json=ns.use_json)


def cmd_comment_list(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    data = client.get(f"/tasks/{tid}/comments", {"order_by": ns.order})
    emit(data, use_json=ns.use_json, text_fn=_print_comments)


def cmd_comment_add(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    data = client.put(f"/tasks/{tid}/comments", {"comment": ns.message})
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_comments([item]))


def cmd_comment_update(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    data = client.post(f"/tasks/{tid}/comments/{ns.comment}", {"comment": ns.message})
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_comments([item]))


def cmd_comment_delete(client: ClientLike, ns: argparse.Namespace) -> None:
    _require_yes(ns)
    tid = resolvers.task_id(client, ns.task)
    data = client.delete(f"/tasks/{tid}/comments/{ns.comment}")
    emit(data or {"task_id": tid, "deleted_comment": ns.comment}, use_json=ns.use_json)


def cmd_notification_list(client: ClientLike, ns: argparse.Namespace) -> None:
    data = _filtered_notifications(client, ns.kind, unread=ns.unread)
    emit(data, use_json=ns.use_json, text_fn=_print_notifications)


def cmd_notification_read(client: ClientLike, ns: argparse.Namespace) -> None:
    data = client.post(f"/notifications/{ns.id}", {"read": True})
    emit(data, use_json=ns.use_json)


def cmd_notification_read_all(client: ClientLike, ns: argparse.Namespace) -> None:
    notifications = _filtered_notifications(client, ns.kind, unread=True)
    ids = [item["id"] for item in notifications if isinstance(item.get("id"), int)]
    for notification_id in ids:
        client.post(f"/notifications/{notification_id}", {"read": True})
    emit({"read": ids, "count": len(ids)}, use_json=ns.use_json)


def cmd_view_list(client: ClientLike, ns: argparse.Namespace) -> None:
    pid = resolvers.project_id(client, ns.project)
    data = client.get(f"/projects/{pid}/views")
    emit(data, use_json=ns.use_json, text_fn=_print_views)


def cmd_view_show(client: ClientLike, ns: argparse.Namespace) -> None:
    pid = resolvers.project_id(client, ns.project)
    vid = resolvers.view_id(client, pid, ns.view)
    data = client.get(f"/projects/{pid}/views/{vid}")
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_views([item]))


def cmd_view_create(client: ClientLike, ns: argparse.Namespace) -> None:
    pid = resolvers.project_id(client, ns.project)
    body = _clean({"title": ns.title, "view_kind": ns.kind, "filter": _filter_obj(ns.filter)})
    data = client.put(f"/projects/{pid}/views", body)
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_views([item]))


def cmd_view_update(client: ClientLike, ns: argparse.Namespace) -> None:
    pid = resolvers.project_id(client, ns.project)
    vid = resolvers.view_id(client, pid, ns.view)
    body = _clean(
        {
            "title": ns.title,
            "view_kind": ns.kind,
            "bucket_configuration_mode": ns.bucket_mode,
        }
    )
    if ns.filter is not None:
        body["filter"] = _filter_obj(ns.filter)
    if ns.clear_filter:
        body["filter"] = {"filter": ""}
    if ns.bucket_filter:
        body["bucket_configuration"] = [_bucket_filter(item) for item in ns.bucket_filter]
        body.setdefault("bucket_configuration_mode", "filter")
    if not body:
        raise InputError("no view fields to update")
    data = client.post(f"/projects/{pid}/views/{vid}", body)
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_views([item]))


def cmd_view_delete(client: ClientLike, ns: argparse.Namespace) -> None:
    _require_yes(ns)
    pid = resolvers.project_id(client, ns.project)
    vid = resolvers.view_id(client, pid, ns.view)
    data = client.delete(f"/projects/{pid}/views/{vid}")
    emit(data or {"deleted": vid}, use_json=ns.use_json)


def cmd_bucket_list(client: ClientLike, ns: argparse.Namespace) -> None:
    pid, vid = _project_view_ids(client, ns)
    data = client.get(f"/projects/{pid}/views/{vid}/buckets")
    emit(data, use_json=ns.use_json, text_fn=_print_buckets)


def cmd_bucket_create(client: ClientLike, ns: argparse.Namespace) -> None:
    pid, vid = _project_view_ids(client, ns)
    data = client.put(
        f"/projects/{pid}/views/{vid}/buckets", _clean({"title": ns.title, "limit": ns.limit})
    )
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_buckets([item]))


def cmd_bucket_update(client: ClientLike, ns: argparse.Namespace) -> None:
    pid, vid = _project_view_ids(client, ns)
    bid = resolvers.bucket_id(client, pid, vid, ns.bucket)
    body = _clean({"title": ns.title, "limit": ns.limit})
    if not body:
        raise InputError("no bucket fields to update")
    data = client.post(f"/projects/{pid}/views/{vid}/buckets/{bid}", body)
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_buckets([item]))


def cmd_bucket_move_task(client: ClientLike, ns: argparse.Namespace) -> None:
    pid, vid = _project_view_ids(client, ns)
    bid = resolvers.bucket_id(client, pid, vid, ns.bucket)
    tid = resolvers.task_id(client, ns.task)
    data = client.post(
        f"/projects/{pid}/views/{vid}/buckets/{bid}/tasks",
        {"task_id": tid, "bucket_id": bid, "project_view_id": vid},
    )
    emit(data, use_json=ns.use_json)


def cmd_bucket_delete(client: ClientLike, ns: argparse.Namespace) -> None:
    _require_yes(ns)
    pid, vid = _project_view_ids(client, ns)
    bid = resolvers.bucket_id(client, pid, vid, ns.bucket)
    data = client.delete(f"/projects/{pid}/views/{vid}/buckets/{bid}")
    emit(data or {"deleted": bid}, use_json=ns.use_json)


def _project_view_ids(client: ClientLike, ns: argparse.Namespace) -> tuple[int, int]:
    pid = resolvers.project_id(client, ns.project)
    vid = resolvers.view_id(client, pid, ns.view)
    return pid, vid


def _require_yes(ns: argparse.Namespace) -> None:
    if not ns.yes:
        raise InputError("destructive operation requires --yes")


def _clean(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if value is not None}


def _filter_obj(value: str | None) -> dict[str, Any] | None:
    return None if value is None else {"filter": value}


def _bucket_filter(value: str) -> dict[str, Any]:
    title, sep, filter_query = value.partition("=")
    if not sep or not title.strip() or not filter_query.strip():
        raise InputError("bucket filters must use TITLE=FILTER syntax")
    return {"title": title.strip(), "filter": {"filter": filter_query.strip()}}


def _project_filter(client: ClientLike, ref: str | None) -> str | None:
    if not ref:
        return None
    return f"project_id = {resolvers.project_id(client, ref)}"


def _combine_filter(left: str | None, right: str | None) -> str | None:
    if left and right:
        return f"({left}) && ({right})"
    return left or right


def _filtered_notifications(client: ClientLike, kind: str, *, unread: bool) -> list[dict[str, Any]]:
    names = DUE_NOTIFICATION_NAMES[kind]
    items = client.paginate("/notifications")
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("name") not in names:
            continue
        if unread and item.get("read_at"):
            continue
        result.append(item)
    return result


def _print_projects(items: Any) -> None:
    rows = [
        [
            str(item.get("id", "-")),
            short(item.get("title")),
            "yes" if item.get("is_archived") else "no",
        ]
        for item in _as_dicts(items)
    ]
    emit_table(["id", "title", "archived"], rows)


def _print_tasks(items: Any) -> None:
    rows = [
        [
            str(item.get("id", "-")),
            short(item.get("identifier")),
            "done" if item.get("done") else "open",
            short(item.get("title")),
            ts(item.get("due_date")),
        ]
        for item in _as_dicts(items)
    ]
    emit_table(["id", "identifier", "state", "title", "due"], rows)


def _print_labels(items: Any) -> None:
    rows = [
        [str(item.get("id", "-")), short(item.get("title")), short(item.get("hex_color"))]
        for item in _as_dicts(items)
    ]
    emit_table(["id", "title", "color"], rows)


def _print_comments(items: Any) -> None:
    rows = [
        [str(item.get("id", "-")), ts(item.get("created")), short(item.get("comment"))]
        for item in _as_dicts(items)
    ]
    emit_table(["id", "created", "comment"], rows)


def _print_notifications(items: Any) -> None:
    rows = [
        [
            str(item.get("id", "-")),
            short(item.get("name")),
            "read" if item.get("read_at") else "unread",
            ts(item.get("created")),
        ]
        for item in _as_dicts(items)
    ]
    emit_table(["id", "name", "state", "created"], rows)


def _print_views(items: Any) -> None:
    rows = [
        [
            str(item.get("id", "-")),
            short(item.get("title")),
            short(item.get("view_kind")),
            short(item.get("bucket_configuration_mode")),
        ]
        for item in _as_dicts(items)
    ]
    emit_table(["id", "title", "kind", "bucket_mode"], rows)


def _print_buckets(items: Any) -> None:
    rows = [
        [str(item.get("id", "-")), short(item.get("title")), short(item.get("limit"))]
        for item in _as_dicts(items)
    ]
    emit_table(["id", "title", "limit"], rows)


def _as_dicts(items: Any) -> list[dict[str, Any]]:
    if isinstance(items, dict):
        return [items]
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []
