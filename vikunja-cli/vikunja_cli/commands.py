# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Command handlers for vikunja-cli."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Protocol

from vikunja_cli import resolvers, templates
from vikunja_cli.errors import CLIError, InputError
from vikunja_cli.output import emit, emit_table, read_json_input, short, ts

DUE_NOTIFICATION_NAMES = {
    "reminder": {"task.reminder"},
    "overdue": {"task.undone.overdue"},
    "due": {"task.reminder", "task.undone.overdue"},
}

WORKFLOW_LABEL_TITLES = [
    "state:next",
    "state:waiting",
    "state:someday",
    "type:backlog",
    "type:bugfix",
    "type:communication",
    "type:decision",
    "type:submission",
    "type:workaround",
]

RELATION_KINDS = [
    "blocked",
    "blocking",
    "subtask",
    "parenttask",
    "precedes",
    "follows",
    "related",
]


class ClientLike(Protocol):
    def get(self, path: str, query: dict[str, Any] | None = None) -> Any: ...

    def post(
        self, path: str, body: Any = None, query: dict[str, Any] | None = None
    ) -> Any: ...

    def put(
        self, path: str, body: Any = None, query: dict[str, Any] | None = None
    ) -> Any: ...

    def delete(self, path: str, query: dict[str, Any] | None = None) -> Any: ...

    def upload_task_attachments(self, task_id: int, files: list[Path]) -> Any: ...

    def download_task_attachment(self, task_id: int, attachment_id: int) -> Any: ...

    def paginate(
        self,
        path: str,
        query: dict[str, Any] | None = None,
        *,
        per_page: int = 50,
        max_pages: int = 100,
    ) -> list[Any]: ...


def cmd_template_list(_client: ClientLike | None, ns: argparse.Namespace) -> None:
    template_dir = Path(ns.template_dir).expanduser() if ns.template_dir else None
    data = templates.list_templates(template_dir)
    emit(data, use_json=ns.use_json, text_fn=_print_template_names)


def cmd_template_show(_client: ClientLike | None, ns: argparse.Namespace) -> None:
    template_dir = Path(ns.template_dir).expanduser() if ns.template_dir else None
    loaded = templates.load_template(ns.template, template_dir=template_dir)
    data = {
        "template": loaded.name,
        "template_path": str(loaded.spec_path),
        "spec_path": str(loaded.spec_path),
        "defaults": loaded.defaults,
        "schema": loaded.schema,
        "body": loaded.spec_path.read_text(),
    }
    emit(data, use_json=ns.use_json)


def cmd_template_render(_client: ClientLike | None, ns: argparse.Namespace) -> None:
    context = read_json_input(ns.context)
    if not isinstance(context, dict):
        raise InputError("template context must be a JSON object")
    template_dir = Path(ns.template_dir).expanduser() if ns.template_dir else None
    data = templates.render_template(ns.template, context, template_dir=template_dir)
    emit(data, use_json=ns.use_json, text_fn=_print_template_render)


def cmd_template_validate(_client: ClientLike | None, ns: argparse.Namespace) -> None:
    if bool(ns.template) == bool(ns.all):
        raise InputError("template validate requires exactly one of TEMPLATE or --all")
    template_dir = Path(ns.template_dir).expanduser() if ns.template_dir else None
    data = (
        templates.validate_templates(template_dir)
        if ns.all
        else [templates.validate_template(ns.template, template_dir=template_dir)]
    )
    emit(data, use_json=ns.use_json, text_fn=_print_template_validation)
    if any(record["errors"] for record in data):
        raise InputError("template validation failed")


def cmd_template_required(_client: ClientLike | None, ns: argparse.Namespace) -> None:
    template_dir = Path(ns.template_dir).expanduser() if ns.template_dir else None
    data = templates.template_required(ns.template, template_dir=template_dir)
    emit(data, use_json=ns.use_json)


def cmd_template_schema(_client: ClientLike | None, ns: argparse.Namespace) -> None:
    template_dir = Path(ns.template_dir).expanduser() if ns.template_dir else None
    data = templates.template_schema(ns.template, template_dir=template_dir)
    emit(data, use_json=ns.use_json)


def cmd_project_list(client: ClientLike, ns: argparse.Namespace) -> None:
    query = {"s": ns.search, "is_archived": "true" if ns.archived else None}
    data = (
        client.paginate("/projects", query)
        if ns.all
        else client.get("/projects", query)
    )
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
            "parent_project_id": resolvers.project_id(client, ns.parent)
            if ns.parent
            else None,
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
    rendered: dict[str, Any] | None = None
    defaults: dict[str, Any] = {}
    if getattr(ns, "template", None):
        if not getattr(ns, "context", None):
            raise InputError("--context is required with --template")
        context = read_json_input(ns.context)
        if not isinstance(context, dict):
            raise InputError("template context must be a JSON object")
        template_dir = (
            Path(ns.template_dir).expanduser()
            if getattr(ns, "template_dir", None)
            else None
        )
        rendered = templates.render_template(
            ns.template, context, template_dir=template_dir
        )
        missing = rendered.get("missing_required")
        if (
            isinstance(missing, list)
            and missing
            and not getattr(ns, "allow_missing", False)
        ):
            fields = ", ".join(str(item) for item in missing)
            raise InputError(f"template missing required fields: {fields}")
        raw_defaults = rendered.get("defaults", {})
        if isinstance(raw_defaults, dict):
            defaults = raw_defaults

    attachment_files = [_input_file(item) for item in getattr(ns, "attach", None) or []]

    description = ns.description
    if description is None and rendered is not None:
        raw_description = rendered.get("description_html")
        if isinstance(raw_description, str):
            description = raw_description
    priority = ns.priority
    if priority is None:
        priority = _template_default_priority(defaults)

    default_label_refs = (
        _template_default_label_refs(client, defaults) if rendered is not None else []
    )

    pid = resolvers.project_id(client, ns.project)
    body = _clean(
        {
            "title": ns.title,
            "description": description,
            "due_date": ns.due,
            "start_date": ns.start,
            "end_date": ns.end,
            "priority": priority,
            "hex_color": ns.color,
            "reminders": _task_reminders(ns),
        }
    )
    data = client.put(f"/projects/{pid}/tasks", body)
    labels_result = None
    if default_label_refs:
        labels_result = _apply_label_refs(client, data, default_label_refs)
    attachment_result = None
    if attachment_files:
        attachment_result = _upload_created_task_attachments(
            client, data, attachment_files
        )
    result = _task_create_result(data, labels_result, attachment_result)
    emit(result, use_json=ns.use_json, text_fn=_print_task_create_result)


def cmd_task_update(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    project = getattr(ns, "project", None)
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
            "project_id": resolvers.project_id(client, project) if project else None,
            "reminders": _task_reminders(ns),
        }
    )
    if not body:
        raise InputError("no task fields to update")
    data = client.post(f"/tasks/{tid}", body)
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_tasks([item]))


def cmd_task_move(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    pid = resolvers.project_id(client, ns.project)
    data = client.post(f"/tasks/{tid}", {"project_id": pid})
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_tasks([item]))


def cmd_task_transition(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    task = client.get(f"/tasks/{tid}")
    target_title = f"state:{ns.state}"
    target_id = resolvers.label_id(client, target_title)
    labels = [*_preserved_label_refs(task), {"id": target_id}]
    labels_result = client.post(f"/tasks/{tid}/labels/bulk", {"labels": labels})
    comment_result = None
    if ns.comment:
        comment_result = client.put(f"/tasks/{tid}/comments", {"comment": ns.comment})
    result = {
        "task_id": tid,
        "state_label": {"id": target_id, "title": target_title},
        "labels_result": labels_result,
    }
    if comment_result is not None:
        result["comment_result"] = comment_result
    emit(result, use_json=ns.use_json, text_fn=_print_task_transition)


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
    tid = resolvers.task_id(client, ns.task)
    data = client.delete(f"/tasks/{tid}")
    emit(data or {"deleted": tid}, use_json=ns.use_json)


def cmd_relation_list(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    task = client.get(f"/tasks/{tid}")
    if not isinstance(task, dict):
        raise InputError("task show response was not an object")
    related = task.get("related_tasks", {})
    emit(related, use_json=ns.use_json, text_fn=_print_relations)


def cmd_relation_add(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    other_id = resolvers.task_id(client, ns.other)
    data = client.put(
        f"/tasks/{tid}/relations",
        {"other_task_id": other_id, "relation_kind": ns.kind},
    )
    emit(data, use_json=ns.use_json)


def cmd_relation_remove(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    other_id = resolvers.task_id(client, ns.other)
    data = client.delete(f"/tasks/{tid}/relations/{ns.kind}/{other_id}")
    emit(
        data
        or {
            "task_id": tid,
            "relation_kind": ns.kind,
            "other_task_id": other_id,
            "removed": True,
        },
        use_json=ns.use_json,
    )


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
        "/labels",
        _clean(
            {"title": ns.title, "description": ns.description, "hex_color": ns.color}
        ),
    )
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_labels([item]))


def cmd_label_update(client: ClientLike, ns: argparse.Namespace) -> None:
    lid = resolvers.label_id(client, ns.label)
    body = _clean(
        {"title": ns.title, "description": ns.description, "hex_color": ns.color}
    )
    if not body:
        raise InputError("no label fields to update")
    data = client.put(f"/labels/{lid}", body)
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_labels([item]))


def cmd_label_delete(client: ClientLike, ns: argparse.Namespace) -> None:
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


def cmd_setup_labels(client: ClientLike, ns: argparse.Namespace) -> None:
    existing_by_title = _existing_workflow_labels(client)
    existing = [
        item for title in WORKFLOW_LABEL_TITLES for item in existing_by_title[title]
    ]
    missing = [title for title in WORKFLOW_LABEL_TITLES if not existing_by_title[title]]
    created: list[Any] = []
    if missing and ns.create:
        for title in missing:
            created.append(client.put("/labels", {"title": title}))
        missing = []
    data = {
        "required": WORKFLOW_LABEL_TITLES,
        "existing": existing,
        "missing": missing,
        "created": created,
        "ok": not missing,
    }
    emit(data, use_json=ns.use_json, text_fn=_print_setup_labels)
    if missing:
        labels = ", ".join(missing)
        raise InputError(f"missing workflow labels: {labels}; rerun with --create")


def cmd_attachment_list(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    data = client.get(f"/tasks/{tid}/attachments")
    if not isinstance(data, list):
        raise InputError("attachment list response was not a list")
    emit(data, use_json=ns.use_json, text_fn=_print_attachments)


def cmd_attachment_upload(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    files = [_input_file(item) for item in ns.files]
    data = client.upload_task_attachments(tid, files)
    emit(data, use_json=ns.use_json)


def cmd_attachment_download(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    output = Path(ns.output).expanduser()
    if output.exists():
        if output.is_dir():
            raise InputError(f"output path is a directory: {output}")
        raise InputError(f"output file already exists: {output}")
    payload = client.download_task_attachment(tid, ns.attachment)
    if not isinstance(payload, bytes):
        raise InputError("attachment download response was not bytes")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        raise InputError(f"output parent is not a directory: {output.parent}") from None
    output.write_bytes(payload)
    emit(
        {
            "task_id": tid,
            "attachment_id": ns.attachment,
            "output": str(output),
            "bytes": len(payload),
        },
        use_json=ns.use_json,
    )


def cmd_attachment_delete(client: ClientLike, ns: argparse.Namespace) -> None:
    tid = resolvers.task_id(client, ns.task)
    data = client.delete(f"/tasks/{tid}/attachments/{ns.attachment}")
    emit(
        data or {"task_id": tid, "deleted_attachment": ns.attachment},
        use_json=ns.use_json,
    )


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
    body = _clean(
        {"title": ns.title, "view_kind": ns.kind, "filter": _filter_obj(ns.filter)}
    )
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
        body["bucket_configuration"] = [
            _bucket_filter(item) for item in ns.bucket_filter
        ]
        body.setdefault("bucket_configuration_mode", "filter")
    if not body:
        raise InputError("no view fields to update")
    data = client.post(f"/projects/{pid}/views/{vid}", body)
    emit(data, use_json=ns.use_json, text_fn=lambda item: _print_views([item]))


def cmd_view_delete(client: ClientLike, ns: argparse.Namespace) -> None:
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
        f"/projects/{pid}/views/{vid}/buckets",
        _clean({"title": ns.title, "limit": ns.limit}),
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
    pid, vid = _project_view_ids(client, ns)
    bid = resolvers.bucket_id(client, pid, vid, ns.bucket)
    data = client.delete(f"/projects/{pid}/views/{vid}/buckets/{bid}")
    emit(data or {"deleted": bid}, use_json=ns.use_json)


def _project_view_ids(client: ClientLike, ns: argparse.Namespace) -> tuple[int, int]:
    pid = resolvers.project_id(client, ns.project)
    vid = resolvers.view_id(client, pid, ns.view)
    return pid, vid


def _clean(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if value is not None}


def _template_default_priority(defaults: dict[str, Any]) -> int | None:
    value = defaults.get("priority")
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise InputError("template default priority must be an integer")
    return value


def _template_default_label_refs(
    client: ClientLike, defaults: dict[str, Any]
) -> list[dict[str, int]]:
    return [
        {"id": resolvers.label_id(client, title)}
        for title in _template_default_label_titles(defaults)
    ]


def _apply_label_refs(
    client: ClientLike, created_task: Any, labels: list[dict[str, int]]
) -> Any:
    task_id = _created_task_id(created_task, "apply template labels")
    return client.post(f"/tasks/{task_id}/labels/bulk", {"labels": labels})


def _upload_created_task_attachments(
    client: ClientLike, created_task: Any, files: list[Path]
) -> dict[str, Any]:
    task_id = _created_task_id(created_task, "upload attachments")
    uploads: list[dict[str, Any]] = []
    for file in files:
        try:
            upload_result = client.upload_task_attachments(task_id, [file])
        except CLIError as exc:
            raise CLIError(
                f"failed to upload attachment after creating task {task_id}: {file}: {exc}"
            ) from exc
        uploads.append({"file": str(file), "result": upload_result})
    return {"task_id": task_id, "uploads": uploads}


def _task_create_result(
    task: Any, labels_result: Any | None, attachment_result: dict[str, Any] | None
) -> Any:
    if attachment_result is None:
        return task
    result = {
        "task": task,
        "task_id": attachment_result["task_id"],
        "attachments": attachment_result,
    }
    if labels_result is not None:
        result["labels_result"] = labels_result
    return result


def _created_task_id(created_task: Any, purpose: str) -> int:
    if not isinstance(created_task, dict):
        raise InputError(f"created task response has no numeric id needed to {purpose}")
    value = created_task.get("id")
    if not isinstance(value, int) or isinstance(value, bool):
        raise InputError(f"created task response has no numeric id needed to {purpose}")
    return value


def _template_default_label_titles(defaults: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()

    def add(title: str) -> None:
        normalized = title.strip()
        if not normalized:
            raise InputError("template default label titles must not be empty")
        if normalized in seen:
            return
        seen.add(normalized)
        titles.append(normalized)

    raw_labels = defaults.get("labels")
    if raw_labels is not None:
        if not isinstance(raw_labels, list):
            raise InputError("template default labels must be a list of strings")
        for item in raw_labels:
            if not isinstance(item, str):
                raise InputError("template default labels must be a list of strings")
            add(item)

    for field in ("type", "label"):
        if field in defaults:
            raise InputError(f"template default {field} is unsupported; use labels")

    return titles


def _task_reminders(ns: argparse.Namespace) -> list[dict[str, str]] | None:
    reminders = getattr(ns, "reminder", None)
    if not reminders:
        return None
    return [{"reminder": item} for item in reminders]


def _existing_workflow_labels(client: ClientLike) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        title: [] for title in WORKFLOW_LABEL_TITLES
    }
    for item in client.paginate("/labels"):
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if isinstance(title, str) and title in result:
            result[title].append(item)
    return result


def _filter_obj(value: str | None) -> dict[str, Any] | None:
    return None if value is None else {"filter": value}


def _input_file(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.exists():
        raise InputError(f"file not found: {path}")
    if not path.is_file():
        raise InputError(f"not a file: {path}")
    try:
        with path.open("rb"):
            pass
    except OSError as exc:
        raise InputError(f"file is not readable: {path}: {exc}") from exc
    return path


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


def _preserved_label_refs(task: Any) -> list[dict[str, int]]:
    if not isinstance(task, dict):
        return []
    labels = task.get("labels")
    if not isinstance(labels, list):
        return []
    preserved: list[dict[str, int]] = []
    for label in labels:
        if not isinstance(label, dict):
            continue
        title = label.get("title")
        if isinstance(title, str) and title.startswith("state:"):
            continue
        label_id = label.get("id")
        if isinstance(label_id, int):
            preserved.append({"id": label_id})
    return preserved


def _filtered_notifications(
    client: ClientLike, kind: str, *, unread: bool
) -> list[dict[str, Any]]:
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


def _print_template_names(items: Any) -> None:
    if isinstance(items, list):
        for item in items:
            print(short(item))


def _print_template_render(item: Any) -> None:
    if not isinstance(item, dict):
        return
    print(short(item.get("description")), end="")
    missing = item.get("missing_required")
    if isinstance(missing, list) and missing:
        print("\nMissing required fields:")
        for field in missing:
            print(f"- {field}")


def _print_template_validation(items: Any) -> None:
    records = _as_dicts(items)
    if not records:
        print("No templates found")
        return
    ok_count = 0
    for record in records:
        ok = bool(record.get("ok"))
        if ok:
            ok_count += 1
        status = "ok" if ok else "error"
        print(f"{short(record.get('template'))}: {status}")
        for error in _as_strings(record.get("errors")):
            print(f"  error: {error}")
        for warning in _as_strings(record.get("warnings")):
            print(f"  warning: {warning}")
    print(f"{ok_count}/{len(records)} templates valid")


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
        [
            str(item.get("id", "-")),
            short(item.get("title")),
            short(item.get("hex_color")),
        ]
        for item in _as_dicts(items)
    ]
    emit_table(["id", "title", "color"], rows)


def _print_relations(item: Any) -> None:
    rows: list[list[str]] = []
    if isinstance(item, dict):
        for kind, tasks in item.items():
            for task in _as_dicts(tasks):
                rows.append(
                    [
                        short(kind),
                        str(task.get("id", "-")),
                        short(task.get("identifier")),
                        short(task.get("title")),
                    ]
                )
    emit_table(["kind", "id", "identifier", "title"], rows)


def _print_attachments(items: Any) -> None:
    rows = []
    for item in _as_dicts(items):
        file_info = item.get("file")
        if not isinstance(file_info, dict):
            file_info = {}
        rows.append(
            [
                str(item.get("id", "-")),
                short(file_info.get("name")),
                short(file_info.get("mime")),
                short(file_info.get("size")),
                ts(item.get("created") or file_info.get("created")),
            ]
        )
    emit_table(["id", "name", "mime", "size", "created"], rows)


def _print_comments(items: Any) -> None:
    rows = [
        [str(item.get("id", "-")), ts(item.get("created")), short(item.get("comment"))]
        for item in _as_dicts(items)
    ]
    emit_table(["id", "created", "comment"], rows)


def _print_task_transition(item: Any) -> None:
    if not isinstance(item, dict):
        return
    state_label = item.get("state_label")
    title = state_label.get("title") if isinstance(state_label, dict) else "-"
    comment = " with comment" if item.get("comment_result") is not None else ""
    print(f"task {short(item.get('task_id'))} -> {short(title)}{comment}")


def _print_task_create_result(item: Any) -> None:
    if isinstance(item, dict) and "task" in item and "attachments" in item:
        attachments = item.get("attachments")
        uploads = attachments.get("uploads") if isinstance(attachments, dict) else None
        upload_count = len(uploads) if isinstance(uploads, list) else 0
        print(f"task {short(item.get('task_id'))} created; attachments: {upload_count}")
        return
    _print_tasks([item])


def _print_setup_labels(item: Any) -> None:
    if not isinstance(item, dict):
        return
    missing = item.get("missing")
    created = item.get("created")
    existing = item.get("existing")
    if isinstance(missing, list) and missing:
        print("missing workflow labels: " + ", ".join(str(label) for label in missing))
        return
    created_count = len(created) if isinstance(created, list) else 0
    existing_count = len(existing) if isinstance(existing, list) else 0
    if created_count:
        print(f"workflow labels ok; created {created_count}")
    else:
        print(f"workflow labels ok; existing {existing_count}")


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


def _as_strings(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, str)]
