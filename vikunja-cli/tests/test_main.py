from __future__ import annotations

import pytest

from pathlib import Path
from unittest.mock import patch
import json

from vikunja_cli.main import _HANDLERS, _build_parser, main


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


def test_relation_add_parser_accepts_safe_kinds_and_dispatches() -> None:
    ns = _build_parser().parse_args(
        ["relation", "add", "--task", "PROJ-1", "--kind", "blocked", "--other", "PROJ-2"]
    )

    assert ns.command == "relation"
    assert ns.subcmd == "add"
    assert ns.task == "PROJ-1"
    assert ns.kind == "blocked"
    assert ns.other == "PROJ-2"
    assert ("relation", "add") in _HANDLERS


def test_relation_list_parser_accepts_task_and_dispatches() -> None:
    ns = _build_parser().parse_args(["relation", "list", "--task", "PROJ-1"])

    assert ns.command == "relation"
    assert ns.subcmd == "list"
    assert ns.task == "PROJ-1"
    assert ("relation", "list") in _HANDLERS


def test_relation_remove_parser_accepts_safe_kinds_and_dispatches() -> None:
    ns = _build_parser().parse_args(
        ["relation", "remove", "--task", "PROJ-1", "--kind", "subtask", "--other", "PROJ-2"]
    )

    assert ns.command == "relation"
    assert ns.subcmd == "remove"
    assert ns.kind == "subtask"
    assert ("relation", "remove") in _HANDLERS


def test_template_schema_parser_accepts_template_and_dispatches() -> None:
    ns = _build_parser().parse_args(["template", "schema", "submission"])

    assert ns.command == "template"
    assert ns.subcmd == "schema"
    assert ns.template == "submission"
    assert ("template", "schema") in _HANDLERS


def test_setup_parser_accepts_command_config() -> None:
    ns = _build_parser().parse_args(
        [
            "--config",
            "/tmp/vikunja.json",
            "setup",
            "--base-url",
            "https://vikunja.example.com",
            "--api-key-command",
            "printf token",
        ]
    )

    assert ns.config == "/tmp/vikunja.json"
    assert ns.command == "setup"
    assert ns.base_url == "https://vikunja.example.com"
    assert ns.api_key_command == "printf token"


def test_setup_writes_config_and_checks_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"

    with patch(
        "sys.argv",
        [
            "vikunja-cli",
            "--config",
            str(config),
            "setup",
            "--base-url",
            "https://vikunja.example.com/",
            "--api-key-command",
            "printf token",
        ],
    ):
        main()

    data = json.loads(config.read_text())
    assert data == {
        "base_url": "https://vikunja.example.com",
        "api_key_command": "printf token",
    }
    out = capsys.readouterr().out
    assert f"Wrote {config}" in out
    assert "API key command works" in out
    assert "token" not in out.replace("API key command works", "")


def test_label_ensure_parser_accepts_create() -> None:
    ns = _build_parser().parse_args(["label", "ensure", "--create"])

    assert ns.command == "label"
    assert ns.subcmd == "ensure"
    assert ns.create is True


def test_label_ensure_parser_defaults_to_check_only() -> None:
    ns = _build_parser().parse_args(["label", "ensure"])

    assert ns.command == "label"
    assert ns.subcmd == "ensure"
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
    assert ("template", "validate") in _HANDLERS


def test_template_required_parser_dispatches() -> None:
    ns = _build_parser().parse_args(
        ["template", "required", "submission", "--template-dir", "templates"]
    )

    assert ns.command == "template"
    assert ns.subcmd == "required"
    assert ns.template == "submission"
    assert ns.template_dir == "templates"
    assert ("template", "required") in _HANDLERS
