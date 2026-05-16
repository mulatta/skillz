from __future__ import annotations

import pytest

from vikunja_cli.main import _HANDLERS, _build_parser


def test_task_update_parser_accepts_title_and_project() -> None:
    ns = _build_parser().parse_args(
        ["task", "update", "5", "--title", "Renamed", "--project", "Inbox"]
    )

    assert ns.command == "task"
    assert ns.subcmd == "update"
    assert ns.task == "5"
    assert ns.title == "Renamed"
    assert ns.project == "Inbox"


def test_task_create_parser_accepts_repeated_reminders() -> None:
    ns = _build_parser().parse_args(
        [
            "task",
            "create",
            "--project",
            "Inbox",
            "--title",
            "Call Kim",
            "--reminder",
            "2026-05-15T09:00:00Z",
            "--reminder",
            "2026-05-15T18:00:00Z",
        ]
    )

    assert ns.command == "task"
    assert ns.subcmd == "create"
    assert ns.reminder == ["2026-05-15T09:00:00Z", "2026-05-15T18:00:00Z"]


def test_task_create_parser_accepts_repeated_attachments() -> None:
    ns = _build_parser().parse_args(
        [
            "task",
            "create",
            "--project",
            "Inbox",
            "--title",
            "Call Kim",
            "--attach",
            "a.txt",
            "--attach",
            "b.txt",
        ]
    )

    assert ns.command == "task"
    assert ns.subcmd == "create"
    assert ns.attach == ["a.txt", "b.txt"]


def test_task_transition_parser_rejects_relation_backed_waiting_upstream() -> None:
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["task", "transition", "5", "--state", "waiting-upstream"])


def test_task_move_parser_accepts_target_project() -> None:
    ns = _build_parser().parse_args(["task", "move", "5", "--project", "Inbox"])

    assert ns.command == "task"
    assert ns.subcmd == "move"
    assert ns.task == "5"
    assert ns.project == "Inbox"


def test_setup_labels_parser_accepts_create() -> None:
    ns = _build_parser().parse_args(["setup", "labels", "--create"])

    assert ns.command == "setup"
    assert ns.subcmd == "labels"
    assert ns.create is True


def test_setup_labels_parser_defaults_to_check_only() -> None:
    ns = _build_parser().parse_args(["setup", "labels"])

    assert ns.command == "setup"
    assert ns.subcmd == "labels"
    assert ns.create is False


def test_attachment_upload_parser_accepts_repeated_files() -> None:
    ns = _build_parser().parse_args(
        ["attachment", "upload", "--task", "5", "--file", "a.txt", "--file", "b.txt"]
    )

    assert ns.command == "attachment"
    assert ns.subcmd == "upload"
    assert ns.task == "5"
    assert ns.files == ["a.txt", "b.txt"]


def test_template_validate_parser_dispatches() -> None:
    ns = _build_parser().parse_args(
        ["template", "validate", "submission", "--template-dir", "templates"]
    )

    assert ns.command == "template"
    assert ns.subcmd == "validate"
    assert ns.template == "submission"
    assert ns.template_dir == "templates"
    assert _HANDLERS[("template", "validate")]


def test_template_required_parser_dispatches() -> None:
    ns = _build_parser().parse_args(
        ["template", "required", "submission", "--template-dir", "templates"]
    )

    assert ns.command == "template"
    assert ns.subcmd == "required"
    assert ns.template == "submission"
    assert ns.template_dir == "templates"
    assert _HANDLERS[("template", "required")]
