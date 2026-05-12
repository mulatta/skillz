from __future__ import annotations

import argparse
from typing import Any

from vikunja_cli.commands import (
    cmd_bucket_move_task,
    cmd_label_replace_on_task,
    cmd_notification_read_all,
    cmd_task_list,
    cmd_task_update,
    cmd_view_update,
)


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any, dict[str, Any] | None]] = []
        self.responses: dict[tuple[str, str], Any] = {}

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        self.calls.append(("GET", path, None, query))
        return self.responses.get(("GET", path), [])

    def post(self, path: str, body: Any = None, query: dict[str, Any] | None = None) -> Any:
        self.calls.append(("POST", path, body, query))
        return self.responses.get(("POST", path), {"ok": True})

    def put(self, path: str, body: Any = None, query: dict[str, Any] | None = None) -> Any:
        self.calls.append(("PUT", path, body, query))
        return self.responses.get(("PUT", path), {"ok": True})

    def delete(self, path: str, query: dict[str, Any] | None = None) -> Any:
        self.calls.append(("DELETE", path, None, query))
        return self.responses.get(("DELETE", path), {"ok": True})

    def paginate(
        self,
        path: str,
        query: dict[str, Any] | None = None,
        *,
        per_page: int = 50,
        max_pages: int = 100,
    ) -> list[Any]:
        self.calls.append(("PAGINATE", path, None, query))
        data = self.responses.get(("PAGINATE", path), [])
        assert isinstance(data, list)
        return data


def ns(**kwargs: Any) -> argparse.Namespace:
    defaults = {"use_json": True}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_task_list_combines_project_and_user_filter() -> None:
    client = RecordingClient()

    cmd_task_list(
        client,
        ns(
            project="12",
            filter="done = false",
            search=None,
            sort_by=None,
            order_by=None,
            expand=None,
            all=False,
        ),
    )

    assert client.calls == [
        (
            "GET",
            "/tasks",
            None,
            {
                "s": None,
                "filter": "(done = false) && (project_id = 12)",
                "sort_by": None,
                "order_by": None,
                "expand": None,
            },
        )
    ]


def test_task_update_sends_title_field() -> None:
    client = RecordingClient()

    cmd_task_update(
        client,
        ns(
            task="5",
            title="Renamed",
            description=None,
            due=None,
            start=None,
            end=None,
            priority=None,
            color=None,
            percent_done=None,
        ),
    )

    assert client.calls == [("POST", "/tasks/5", {"title": "Renamed"}, None)]


def test_label_replace_on_task_uses_bulk_endpoint() -> None:
    client = RecordingClient()

    cmd_label_replace_on_task(client, ns(task="5", label=["10", "11"]))

    assert client.calls == [
        ("POST", "/tasks/5/labels/bulk", {"labels": [{"id": 10}, {"id": 11}]}, None)
    ]


def test_notification_read_all_only_marks_due_unread_notifications() -> None:
    client = RecordingClient()
    client.responses[("PAGINATE", "/notifications")] = [
        {"id": 1, "name": "task.reminder", "read_at": None},
        {"id": 2, "name": "task.undone.overdue", "read_at": "2026-05-12T00:00:00Z"},
        {"id": 3, "name": "task.comment", "read_at": None},
    ]

    cmd_notification_read_all(client, ns(kind="due"))

    assert client.calls == [
        ("PAGINATE", "/notifications", None, None),
        ("POST", "/notifications/1", {"read": True}, None),
    ]


def test_view_update_bucket_filters_sets_filter_mode() -> None:
    client = RecordingClient()

    cmd_view_update(
        client,
        ns(
            project="7",
            view="8",
            title=None,
            kind=None,
            filter=None,
            clear_filter=False,
            bucket_mode=None,
            bucket_filter=["Overdue=done = false && due_date < now"],
        ),
    )

    assert client.calls == [
        (
            "POST",
            "/projects/7/views/8",
            {
                "bucket_configuration": [
                    {"title": "Overdue", "filter": {"filter": "done = false && due_date < now"}}
                ],
                "bucket_configuration_mode": "filter",
            },
            None,
        )
    ]


def test_bucket_move_task_resolves_context_and_posts_task_bucket() -> None:
    client = RecordingClient()

    cmd_bucket_move_task(client, ns(project="1", view="2", task="3", bucket="4"))

    assert client.calls == [
        (
            "POST",
            "/projects/1/views/2/buckets/4/tasks",
            {"task_id": 3, "bucket_id": 4, "project_view_id": 2},
            None,
        )
    ]
