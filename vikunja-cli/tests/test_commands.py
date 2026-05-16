from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from vikunja_cli.commands import (
    cmd_attachment_delete,
    cmd_attachment_download,
    cmd_attachment_list,
    cmd_attachment_upload,
    cmd_bucket_move_task,
    cmd_label_replace_on_task,
    cmd_notification_read_all,
    cmd_setup_labels,
    cmd_task_create,
    cmd_task_list,
    cmd_task_move,
    cmd_task_transition,
    cmd_task_update,
    cmd_view_update,
)
from vikunja_cli.errors import CLIError, InputError


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

    def upload_task_attachments(self, task_id: int, files: list[Path]) -> Any:
        self.calls.append(("UPLOAD", f"/tasks/{task_id}/attachments", files, None))
        response = self.responses.get(("UPLOAD", f"/tasks/{task_id}/attachments"), {"ok": True})
        if isinstance(response, Exception):
            raise response
        return response

    def download_task_attachment(self, task_id: int, attachment_id: int) -> Any:
        self.calls.append(("DOWNLOAD", f"/tasks/{task_id}/attachments/{attachment_id}", None, None))
        return self.responses.get(
            ("DOWNLOAD", f"/tasks/{task_id}/attachments/{attachment_id}"), b""
        )

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


def write_task_template(
    root: Path,
    name: str,
    *,
    template: str = "## Goal\n{{ goal }}\n",
    schema: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
) -> Path:
    template_root = root / name
    template_root.mkdir(parents=True)
    (template_root / "template.md.njk").write_text(template)
    (template_root / "schema.json").write_text(json.dumps(schema or {}))
    (template_root / "defaults.json").write_text(json.dumps(defaults or {}))
    return template_root


def write_context(root: Path, value: dict[str, Any]) -> Path:
    path = root / "context.json"
    path.write_text(json.dumps(value))
    return path


def task_create_ns(**kwargs: Any) -> argparse.Namespace:
    defaults = {
        "project": "7",
        "title": "Made from template",
        "description": None,
        "due": None,
        "start": None,
        "end": None,
        "priority": None,
        "color": None,
        "reminder": None,
        "template": None,
        "context": None,
        "allow_missing": False,
        "attach": None,
    }
    defaults.update(kwargs)
    return ns(**defaults)


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
            reminder=None,
        ),
    )

    assert client.calls == [("POST", "/tasks/5", {"title": "Renamed"}, None)]


def test_task_move_posts_project_id_without_numeric_resolver_calls() -> None:
    client = RecordingClient()

    cmd_task_move(client, ns(task="5", project="9"))

    assert client.calls == [("POST", "/tasks/5", {"project_id": 9}, None)]


def test_task_update_sends_project_id_with_other_fields() -> None:
    client = RecordingClient()

    cmd_task_update(
        client,
        ns(
            task="5",
            project="9",
            title="Renamed",
            description=None,
            due=None,
            start=None,
            end=None,
            priority=None,
            color=None,
            percent_done=None,
            reminder=["2026-05-19T09:00:00Z", "2026-05-20T09:00:00Z"],
        ),
    )

    assert client.calls == [
        (
            "POST",
            "/tasks/5",
            {
                "title": "Renamed",
                "project_id": 9,
                "reminders": [
                    {"reminder": "2026-05-19T09:00:00Z"},
                    {"reminder": "2026-05-20T09:00:00Z"},
                ],
            },
            None,
        )
    ]


def test_task_create_without_template_keeps_existing_body() -> None:
    client = RecordingClient()

    cmd_task_create(
        client,
        task_create_ns(
            template=None,
            context=None,
            description="Manual body",
            due="2026-05-20T00:00:00Z",
            priority=3,
            color="#ffaa00",
            reminder=["2026-05-19T09:00:00Z"],
        ),
    )

    assert client.calls == [
        (
            "PUT",
            "/projects/7/tasks",
            {
                "title": "Made from template",
                "description": "Manual body",
                "due_date": "2026-05-20T00:00:00Z",
                "priority": 3,
                "hex_color": "#ffaa00",
                "reminders": [{"reminder": "2026-05-19T09:00:00Z"}],
            },
            None,
        )
    ]


def test_task_create_from_template_uses_rendered_description(tmp_path: Path) -> None:
    client = RecordingClient()
    write_task_template(tmp_path, "submission")
    context = write_context(tmp_path, {"goal": "Ship template create"})

    cmd_task_create(
        client,
        task_create_ns(template="submission", template_dir=str(tmp_path), context=str(context)),
    )

    assert client.calls == [
        (
            "PUT",
            "/projects/7/tasks",
            {"title": "Made from template", "description": "## Goal\nShip template create\n"},
            None,
        )
    ]


def test_task_create_from_template_respects_explicit_description(tmp_path: Path) -> None:
    client = RecordingClient()
    write_task_template(tmp_path, "submission")
    context = write_context(tmp_path, {"goal": "Rendered body"})

    cmd_task_create(
        client,
        task_create_ns(
            template="submission",
            template_dir=str(tmp_path),
            context=str(context),
            description="Explicit body",
        ),
    )

    assert client.calls == [
        (
            "PUT",
            "/projects/7/tasks",
            {"title": "Made from template", "description": "Explicit body"},
            None,
        )
    ]


def test_task_create_from_template_missing_required_fails_by_default(tmp_path: Path) -> None:
    client = RecordingClient()
    write_task_template(tmp_path, "submission", schema={"required": ["goal"]})
    context = write_context(tmp_path, {})

    with pytest.raises(InputError, match="template missing required fields: goal"):
        cmd_task_create(
            client,
            task_create_ns(template="submission", template_dir=str(tmp_path), context=str(context)),
        )

    assert client.calls == []


def test_task_create_from_template_allow_missing_permits_creation(tmp_path: Path) -> None:
    client = RecordingClient()
    write_task_template(tmp_path, "submission", schema={"required": ["goal"]})
    context = write_context(tmp_path, {})

    cmd_task_create(
        client,
        task_create_ns(
            template="submission",
            template_dir=str(tmp_path),
            context=str(context),
            allow_missing=True,
        ),
    )

    assert client.calls == [
        (
            "PUT",
            "/projects/7/tasks",
            {"title": "Made from template", "description": "## Goal\n"},
            None,
        )
    ]


def test_task_create_from_template_default_priority_only_when_absent(tmp_path: Path) -> None:
    write_task_template(tmp_path, "submission", defaults={"priority": 4})
    context = write_context(tmp_path, {"goal": "Prioritize"})

    default_client = RecordingClient()
    cmd_task_create(
        default_client,
        task_create_ns(template="submission", template_dir=str(tmp_path), context=str(context)),
    )

    explicit_client = RecordingClient()
    cmd_task_create(
        explicit_client,
        task_create_ns(
            template="submission",
            template_dir=str(tmp_path),
            context=str(context),
            priority=2,
        ),
    )

    assert default_client.calls[0] == (
        "PUT",
        "/projects/7/tasks",
        {"title": "Made from template", "description": "## Goal\nPrioritize\n", "priority": 4},
        None,
    )
    assert explicit_client.calls[0] == (
        "PUT",
        "/projects/7/tasks",
        {"title": "Made from template", "description": "## Goal\nPrioritize\n", "priority": 2},
        None,
    )


def test_task_create_from_template_applies_default_labels(tmp_path: Path) -> None:
    client = RecordingClient()
    client.responses[("PUT", "/projects/7/tasks")] = {"id": 42, "title": "Made from template"}
    client.responses[("PAGINATE", "/labels")] = [
        {"id": 10, "title": "type:submission"},
        {"id": 11, "title": "state:next"},
    ]
    write_task_template(
        tmp_path,
        "submission",
        defaults={"labels": ["type:submission", "state:next", "state:next"]},
    )
    context = write_context(tmp_path, {"goal": "Label it"})

    cmd_task_create(
        client,
        task_create_ns(template="submission", template_dir=str(tmp_path), context=str(context)),
    )

    assert client.calls == [
        ("PAGINATE", "/labels", None, {"s": "type:submission"}),
        ("PAGINATE", "/labels", None, {"s": "state:next"}),
        (
            "PUT",
            "/projects/7/tasks",
            {"title": "Made from template", "description": "## Goal\nLabel it\n"},
            None,
        ),
        ("POST", "/tasks/42/labels/bulk", {"labels": [{"id": 10}, {"id": 11}]}, None),
    ]


def test_task_create_from_template_resolves_default_labels_before_creation(tmp_path: Path) -> None:
    client = RecordingClient()
    client.responses[("PAGINATE", "/labels")] = []
    write_task_template(tmp_path, "submission", defaults={"labels": ["type:submission"]})
    context = write_context(tmp_path, {"goal": "Missing label"})

    with pytest.raises(InputError, match="no label exactly matches"):
        cmd_task_create(
            client,
            task_create_ns(template="submission", template_dir=str(tmp_path), context=str(context)),
        )

    assert client.calls == [("PAGINATE", "/labels", None, {"s": "type:submission"})]


def test_task_create_from_template_rejects_default_shortcuts(tmp_path: Path) -> None:
    client = RecordingClient()
    write_task_template(tmp_path, "submission", defaults={"type": "submission", "label": "next"})
    context = write_context(tmp_path, {"goal": "No shortcuts"})

    with pytest.raises(InputError, match="template default type is unsupported"):
        cmd_task_create(
            client,
            task_create_ns(template="submission", template_dir=str(tmp_path), context=str(context)),
        )

    assert client.calls == []


def test_task_create_with_attach_rejects_missing_file_before_create(tmp_path: Path) -> None:
    client = RecordingClient()

    with pytest.raises(InputError, match="file not found"):
        cmd_task_create(client, task_create_ns(attach=[str(tmp_path / "missing.txt")]))

    assert client.calls == []


def test_task_create_with_attach_rejects_directory_before_create(tmp_path: Path) -> None:
    client = RecordingClient()

    with pytest.raises(InputError, match="not a file"):
        cmd_task_create(client, task_create_ns(attach=[str(tmp_path)]))

    assert client.calls == []


def test_task_create_with_attach_uploads_each_file_after_creation(tmp_path: Path) -> None:
    client = RecordingClient()
    client.responses[("PUT", "/projects/7/tasks")] = {"id": 44, "title": "Made from template"}
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first")
    second.write_text("second")

    cmd_task_create(client, task_create_ns(attach=[str(first), str(second)]))

    assert client.calls == [
        (
            "PUT",
            "/projects/7/tasks",
            {"title": "Made from template"},
            None,
        ),
        ("UPLOAD", "/tasks/44/attachments", [first], None),
        ("UPLOAD", "/tasks/44/attachments", [second], None),
    ]


def test_task_create_with_attach_requires_created_task_id(tmp_path: Path) -> None:
    client = RecordingClient()
    client.responses[("PUT", "/projects/7/tasks")] = {"title": "Made from template"}
    attachment = tmp_path / "evidence.txt"
    attachment.write_text("proof")

    with pytest.raises(InputError, match="numeric id needed to upload attachments"):
        cmd_task_create(client, task_create_ns(attach=[str(attachment)]))

    assert client.calls == [("PUT", "/projects/7/tasks", {"title": "Made from template"}, None)]


def test_task_create_with_attach_reports_upload_failure_with_task_id_and_file(
    tmp_path: Path,
) -> None:
    client = RecordingClient()
    client.responses[("PUT", "/projects/7/tasks")] = {"id": 45, "title": "Made from template"}
    client.responses[("UPLOAD", "/tasks/45/attachments")] = CLIError("network stopped")
    attachment = tmp_path / "evidence.txt"
    attachment.write_text("proof")

    with pytest.raises(CLIError, match=r"task 45.*evidence\.txt.*network stopped"):
        cmd_task_create(client, task_create_ns(attach=[str(attachment)]))

    assert client.calls == [
        ("PUT", "/projects/7/tasks", {"title": "Made from template"}, None),
        ("UPLOAD", "/tasks/45/attachments", [attachment], None),
    ]


def test_task_create_from_template_with_attach_resolves_labels_before_create(
    tmp_path: Path,
) -> None:
    client = RecordingClient()
    client.responses[("PUT", "/projects/7/tasks")] = {"id": 46, "title": "Made from template"}
    client.responses[("PAGINATE", "/labels")] = [{"id": 10, "title": "type:submission"}]
    write_task_template(tmp_path, "submission", defaults={"labels": ["type:submission"]})
    context = write_context(tmp_path, {"goal": "Attach proof"})
    attachment = tmp_path / "proof.txt"
    attachment.write_text("proof")

    cmd_task_create(
        client,
        task_create_ns(
            template="submission",
            template_dir=str(tmp_path),
            context=str(context),
            attach=[str(attachment)],
        ),
    )

    assert client.calls == [
        ("PAGINATE", "/labels", None, {"s": "type:submission"}),
        (
            "PUT",
            "/projects/7/tasks",
            {"title": "Made from template", "description": "## Goal\nAttach proof\n"},
            None,
        ),
        ("POST", "/tasks/46/labels/bulk", {"labels": [{"id": 10}]}, None),
        ("UPLOAD", "/tasks/46/attachments", [attachment], None),
    ]


def test_task_create_json_result_includes_attachment_uploads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = RecordingClient()
    client.responses[("PUT", "/projects/7/tasks")] = {"id": 47, "title": "Made from template"}
    client.responses[("UPLOAD", "/tasks/47/attachments")] = [{"id": 80}]
    attachment = tmp_path / "proof.txt"
    attachment.write_text("proof")

    cmd_task_create(client, task_create_ns(attach=[str(attachment)]))

    result = json.loads(capsys.readouterr().out)
    assert result == {
        "task": {"id": 47, "title": "Made from template"},
        "task_id": 47,
        "attachments": {
            "task_id": 47,
            "uploads": [{"file": str(attachment), "result": [{"id": 80}]}],
        },
    }


def test_attachment_list_calls_task_attachment_endpoint() -> None:
    client = RecordingClient()
    client.responses[("GET", "/tasks/5/attachments")] = [
        {"id": 7, "file": {"name": "note.txt", "size": 4}}
    ]

    cmd_attachment_list(client, ns(task="5"))

    assert client.calls == [("GET", "/tasks/5/attachments", None, None)]


def test_attachment_delete_requires_yes() -> None:
    client = RecordingClient()

    with pytest.raises(InputError, match="requires --yes"):
        cmd_attachment_delete(client, ns(task="5", attachment=7, yes=False))

    assert client.calls == []


def test_attachment_delete_calls_task_attachment_endpoint() -> None:
    client = RecordingClient()

    cmd_attachment_delete(client, ns(task="5", attachment=7, yes=True))

    assert client.calls == [("DELETE", "/tasks/5/attachments/7", None, None)]


def test_attachment_upload_passes_task_id_and_files(tmp_path: Path) -> None:
    client = RecordingClient()
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first")
    second.write_text("second")

    cmd_attachment_upload(client, ns(task="5", files=[str(first), str(second)]))

    assert client.calls == [("UPLOAD", "/tasks/5/attachments", [first, second], None)]


def test_attachment_upload_rejects_missing_file(tmp_path: Path) -> None:
    client = RecordingClient()

    with pytest.raises(InputError, match="file not found"):
        cmd_attachment_upload(client, ns(task="5", files=[str(tmp_path / "missing.txt")]))

    assert client.calls == []


def test_attachment_download_writes_bytes(tmp_path: Path) -> None:
    client = RecordingClient()
    client.responses[("DOWNLOAD", "/tasks/5/attachments/7")] = b"payload"
    output = tmp_path / "dir" / "file.bin"

    cmd_attachment_download(client, ns(task="5", attachment=7, output=str(output)))

    assert output.read_bytes() == b"payload"
    assert client.calls == [("DOWNLOAD", "/tasks/5/attachments/7", None, None)]


def test_attachment_download_rejects_non_bytes_response(tmp_path: Path) -> None:
    client = RecordingClient()
    client.responses[("DOWNLOAD", "/tasks/5/attachments/7")] = {"id": 7}

    with pytest.raises(InputError, match="not bytes"):
        cmd_attachment_download(client, ns(task="5", attachment=7, output=str(tmp_path / "out")))

    assert not (tmp_path / "out").exists()


def test_attachment_download_rejects_directory_output(tmp_path: Path) -> None:
    client = RecordingClient()

    with pytest.raises(InputError, match="directory"):
        cmd_attachment_download(client, ns(task="5", attachment=7, output=str(tmp_path)))

    assert client.calls == []


def test_label_replace_on_task_uses_bulk_endpoint() -> None:
    client = RecordingClient()

    cmd_label_replace_on_task(client, ns(task="5", label=["10", "11"]))

    assert client.calls == [
        ("POST", "/tasks/5/labels/bulk", {"labels": [{"id": 10}, {"id": 11}]}, None)
    ]


def test_setup_labels_reports_missing_without_create(capsys: pytest.CaptureFixture[str]) -> None:
    client = RecordingClient()
    client.responses[("PAGINATE", "/labels")] = [
        {"id": 10, "title": "state:next"},
        {"id": 11, "title": "state:waiting"},
    ]

    with pytest.raises(InputError, match="missing workflow labels"):
        cmd_setup_labels(client, ns(create=False))

    assert client.calls == [("PAGINATE", "/labels", None, None)]
    data = json.loads(capsys.readouterr().out)
    assert data == {
        "required": [
            "state:next",
            "state:waiting",
            "state:someday",
            "type:backlog",
            "type:bugfix",
            "type:communication",
            "type:decision",
            "type:submission",
            "type:workaround",
        ],
        "existing": [
            {"id": 10, "title": "state:next"},
            {"id": 11, "title": "state:waiting"},
        ],
        "missing": [
            "state:someday",
            "type:backlog",
            "type:bugfix",
            "type:communication",
            "type:decision",
            "type:submission",
            "type:workaround",
        ],
        "created": [],
        "ok": False,
    }


def test_setup_labels_create_creates_missing_workflow_labels(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = RecordingClient()
    client.responses[("PAGINATE", "/labels")] = [{"id": 10, "title": "state:next"}]
    client.responses[("PUT", "/labels")] = {"id": 20, "title": "created"}

    cmd_setup_labels(client, ns(create=True))

    assert client.calls == [
        ("PAGINATE", "/labels", None, None),
        ("PUT", "/labels", {"title": "state:waiting"}, None),
        ("PUT", "/labels", {"title": "state:someday"}, None),
        ("PUT", "/labels", {"title": "type:backlog"}, None),
        ("PUT", "/labels", {"title": "type:bugfix"}, None),
        ("PUT", "/labels", {"title": "type:communication"}, None),
        ("PUT", "/labels", {"title": "type:decision"}, None),
        ("PUT", "/labels", {"title": "type:submission"}, None),
        ("PUT", "/labels", {"title": "type:workaround"}, None),
    ]
    data = json.loads(capsys.readouterr().out)
    assert data["existing"] == [{"id": 10, "title": "state:next"}]
    assert data["missing"] == []
    assert data["created"] == [{"id": 20, "title": "created"}] * 8
    assert data["ok"] is True


def test_setup_labels_does_not_recreate_existing_labels(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = RecordingClient()
    labels = [
        {"id": 10, "title": "state:next"},
        {"id": 11, "title": "state:waiting"},
        {"id": 13, "title": "state:someday"},
        {"id": 14, "title": "type:backlog"},
        {"id": 15, "title": "type:bugfix"},
        {"id": 16, "title": "type:communication"},
        {"id": 17, "title": "type:decision"},
        {"id": 18, "title": "type:submission"},
        {"id": 19, "title": "type:workaround"},
    ]
    client.responses[("PAGINATE", "/labels")] = labels

    cmd_setup_labels(client, ns(create=True))

    assert client.calls == [("PAGINATE", "/labels", None, None)]
    data = json.loads(capsys.readouterr().out)
    assert data["existing"] == labels
    assert data["missing"] == []
    assert data["created"] == []
    assert data["ok"] is True


def test_task_transition_replaces_old_state_label_and_preserves_other_labels() -> None:
    client = RecordingClient()
    client.responses[("GET", "/tasks/5")] = {
        "id": 5,
        "labels": [
            {"id": 10, "title": "area:ops"},
            {"id": 11, "title": "state:waiting"},
            {"id": 12, "title": "priority:high"},
        ],
    }
    client.responses[("PAGINATE", "/labels")] = [{"id": 20, "title": "state:next"}]

    cmd_task_transition(client, ns(task="5", state="next", comment=None))

    assert client.calls == [
        ("GET", "/tasks/5", None, None),
        ("PAGINATE", "/labels", None, {"s": "state:next"}),
        (
            "POST",
            "/tasks/5/labels/bulk",
            {"labels": [{"id": 10}, {"id": 12}, {"id": 20}]},
            None,
        ),
    ]


def test_task_transition_resolves_and_applies_target_state_label() -> None:
    client = RecordingClient()
    client.responses[("GET", "/tasks/5")] = {"id": 5, "labels": []}
    client.responses[("PAGINATE", "/labels")] = [{"id": 21, "title": "state:someday"}]

    cmd_task_transition(client, ns(task="5", state="someday", comment=None))

    assert client.calls[-1] == (
        "POST",
        "/tasks/5/labels/bulk",
        {"labels": [{"id": 21}]},
        None,
    )


def test_task_transition_with_comment_adds_task_comment() -> None:
    client = RecordingClient()
    client.responses[("GET", "/tasks/5")] = {"id": 5, "labels": []}
    client.responses[("PAGINATE", "/labels")] = [{"id": 20, "title": "state:waiting"}]
    client.responses[("PUT", "/tasks/5/comments")] = {"id": 30, "comment": "Blocked by review"}

    cmd_task_transition(client, ns(task="5", state="waiting", comment="Blocked by review"))

    assert client.calls[-1] == (
        "PUT",
        "/tasks/5/comments",
        {"comment": "Blocked by review"},
        None,
    )


def test_task_transition_without_comment_does_not_call_comments_endpoint() -> None:
    client = RecordingClient()
    client.responses[("GET", "/tasks/5")] = {"id": 5, "labels": []}
    client.responses[("PAGINATE", "/labels")] = [{"id": 20, "title": "state:waiting"}]

    cmd_task_transition(client, ns(task="5", state="waiting", comment=None))

    assert all("comments" not in call[1] for call in client.calls)


def test_task_transition_handles_missing_current_labels() -> None:
    client = RecordingClient()
    client.responses[("GET", "/tasks/5")] = {"id": 5}
    client.responses[("PAGINATE", "/labels")] = [{"id": 20, "title": "state:waiting"}]

    cmd_task_transition(client, ns(task="5", state="waiting", comment=None))

    assert client.calls[-1] == (
        "POST",
        "/tasks/5/labels/bulk",
        {"labels": [{"id": 20}]},
        None,
    )


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
