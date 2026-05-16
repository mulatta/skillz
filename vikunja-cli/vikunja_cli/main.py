"""vikunja-cli entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from vikunja_cli.client import Client
from vikunja_cli.commands import (
    RELATION_KINDS,
    cmd_attachment_delete,
    cmd_attachment_download,
    cmd_attachment_list,
    cmd_attachment_upload,
    cmd_bucket_create,
    cmd_bucket_delete,
    cmd_bucket_list,
    cmd_bucket_move_task,
    cmd_bucket_update,
    cmd_comment_add,
    cmd_comment_delete,
    cmd_comment_list,
    cmd_comment_update,
    cmd_label_add_to_task,
    cmd_label_create,
    cmd_label_delete,
    cmd_label_list,
    cmd_label_remove_from_task,
    cmd_label_replace_on_task,
    cmd_label_show,
    cmd_label_update,
    cmd_notification_list,
    cmd_notification_read,
    cmd_notification_read_all,
    cmd_project_create,
    cmd_project_delete,
    cmd_relation_add,
    cmd_relation_list,
    cmd_relation_remove,
    cmd_project_list,
    cmd_project_show,
    cmd_project_update,
    cmd_setup_labels,
    cmd_task_complete,
    cmd_task_create,
    cmd_task_delete,
    cmd_task_duplicate,
    cmd_task_list,
    cmd_task_move,
    cmd_task_reopen,
    cmd_task_show,
    cmd_task_transition,
    cmd_task_update,
    cmd_template_list,
    cmd_template_render,
    cmd_template_required,
    cmd_template_show,
    cmd_template_validate,
    cmd_view_create,
    cmd_view_delete,
    cmd_view_list,
    cmd_view_show,
    cmd_view_update,
)
from vikunja_cli.config import resolve_credentials, run_api_key_command, write_config
from vikunja_cli.errors import CLIError

Handler = Callable[[Any, argparse.Namespace], None]


def _make_client() -> Client:
    base_url, api_key, timeout = resolve_credentials()
    return Client(base_url, api_key, timeout)


def _cmd_bootstrap(ns: argparse.Namespace) -> None:
    config_path = write_config(ns.base_url, ns.api_key_command)
    token = run_api_key_command(ns.api_key_command)
    if not token:
        raise CLIError("api_key_command did not return a token")
    client = Client(ns.base_url, token, ns.timeout)
    user = client.get("/user")
    username = user.get("username") if isinstance(user, dict) else None
    suffix = f" as {username}" if username else ""
    print(f"Configured {config_path}{suffix}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vikunja-cli", description="Agent-oriented Vikunja CLI")
    parser.add_argument("-j", "--json", action="store_true", dest="use_json", help="Output JSON")
    sub = parser.add_subparsers(dest="command")

    s = sub.add_parser("bootstrap", help="Write config and verify API token")
    s.add_argument("--base-url", required=True, help="Vikunja base URL")
    s.add_argument("--api-key-command", required=True, help="Command that prints API token")
    s.add_argument("--timeout", type=int, default=30, help="Verification timeout in seconds")

    _add_setup(sub)
    _add_project(sub)
    _add_task(sub)
    _add_attachment(sub)
    _add_relation(sub)
    _add_label(sub)
    _add_comment(sub)
    _add_notification(sub)
    _add_view(sub)
    _add_bucket(sub)
    _add_template(sub)
    return parser


def _add_setup(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    setup = sub.add_parser("setup", help="Verify or create workflow prerequisites")
    setup_sub = setup.add_subparsers(dest="subcmd")

    s = setup_sub.add_parser("labels", help="Verify or create default workflow labels")
    s.add_argument("--create", action="store_true", help="Create missing workflow labels")


def _add_project(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    project = sub.add_parser("project", help="Manage projects")
    project_sub = project.add_subparsers(dest="subcmd")

    s = project_sub.add_parser("list")
    s.add_argument("--search")
    s.add_argument("--archived", action="store_true", help="Include archived projects")
    s.add_argument("--all", action="store_true", help="Fetch all pages")

    s = project_sub.add_parser("show")
    s.add_argument("project")

    s = project_sub.add_parser("create")
    s.add_argument("--title", required=True)
    s.add_argument("--description")
    s.add_argument("--color")
    s.add_argument("--parent")

    s = project_sub.add_parser("update")
    s.add_argument("project")
    _project_update_args(s)

    s = project_sub.add_parser("archive")
    s.add_argument("project")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(is_archived=True, title=None, description=None, color=None)

    s = project_sub.add_parser("unarchive")
    s.add_argument("project")
    s.set_defaults(is_archived=False, title=None, description=None, color=None)

    s = project_sub.add_parser("delete")
    s.add_argument("project")
    s.add_argument("--yes", action="store_true")


def _project_update_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title")
    parser.add_argument("--description")
    parser.add_argument("--color")
    parser.set_defaults(is_archived=None)


def _add_task(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    task = sub.add_parser("task", help="Manage tasks")
    task_sub = task.add_subparsers(dest="subcmd")

    s = task_sub.add_parser("list")
    s.add_argument("--project")
    s.add_argument("--filter")
    s.add_argument("--search")
    s.add_argument("--sort-by", action="append")
    s.add_argument("--order-by", action="append")
    s.add_argument("--expand")
    s.add_argument("--all", action="store_true")

    s = task_sub.add_parser("show")
    s.add_argument("task")

    s = task_sub.add_parser("create")
    s.add_argument("--project", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--template", help="Render local template into task description")
    s.add_argument("--context", help="JSON template context file, or '-' for stdin")
    s.add_argument(
        "--allow-missing",
        action="store_true",
        help="Allow template creation when required context fields are missing",
    )
    _task_field_args(s)
    s.add_argument("--attach", action="append", help="File to upload after task creation")

    s = task_sub.add_parser("update")
    s.add_argument("task")
    s.add_argument("--title")
    s.add_argument("--project")
    _task_field_args(s)
    s.add_argument("--percent-done", type=float)

    s = task_sub.add_parser("move")
    s.add_argument("task")
    s.add_argument("--project", required=True)

    s = task_sub.add_parser("transition")
    s.add_argument("task")
    s.add_argument("--state", required=True, choices=["waiting", "next", "someday"])
    s.add_argument("--comment")

    for name in ("complete", "reopen", "duplicate"):
        s = task_sub.add_parser(name)
        s.add_argument("task")

    s = task_sub.add_parser("delete")
    s.add_argument("task")
    s.add_argument("--yes", action="store_true")


def _task_field_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--description")
    parser.add_argument("--due")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--priority", type=int)
    parser.add_argument("--color")
    parser.add_argument("--reminder", action="append", help="Absolute reminder timestamp")


def _add_attachment(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    attachment = sub.add_parser("attachment", help="Manage task attachments")
    attachment_sub = attachment.add_subparsers(dest="subcmd")

    s = attachment_sub.add_parser("list")
    s.add_argument("--task", required=True)

    s = attachment_sub.add_parser("upload")
    s.add_argument("--task", required=True)
    s.add_argument("--file", action="append", required=True, dest="files")

    s = attachment_sub.add_parser("download")
    s.add_argument("--task", required=True)
    s.add_argument("--attachment", required=True, type=int)
    s.add_argument("--output", required=True)

    s = attachment_sub.add_parser("delete")
    s.add_argument("--task", required=True)
    s.add_argument("--attachment", required=True, type=int)
    s.add_argument("--yes", action="store_true")


def _add_relation(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    relation = sub.add_parser("relation", help="Manage task relations")
    relation_sub = relation.add_subparsers(dest="subcmd")

    s = relation_sub.add_parser("list")
    s.add_argument("--task", required=True)

    for name in ("add", "remove"):
        s = relation_sub.add_parser(name)
        s.add_argument("--task", required=True)
        s.add_argument("--kind", required=True, choices=RELATION_KINDS)
        s.add_argument("--other", required=True)


def _add_label(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    label = sub.add_parser("label", help="Manage labels")
    label_sub = label.add_subparsers(dest="subcmd")

    s = label_sub.add_parser("list")
    s.add_argument("--search")
    s.add_argument("--all", action="store_true")

    s = label_sub.add_parser("show")
    s.add_argument("label")

    s = label_sub.add_parser("create")
    s.add_argument("--title", required=True)
    _label_field_args(s)

    s = label_sub.add_parser("update")
    s.add_argument("label")
    s.add_argument("--title")
    _label_field_args(s)

    s = label_sub.add_parser("delete")
    s.add_argument("label")
    s.add_argument("--yes", action="store_true")

    s = label_sub.add_parser("add-to-task")
    s.add_argument("--task", required=True)
    s.add_argument("--label", required=True)

    s = label_sub.add_parser("remove-from-task")
    s.add_argument("--task", required=True)
    s.add_argument("--label", required=True)

    s = label_sub.add_parser("replace-on-task")
    s.add_argument("--task", required=True)
    s.add_argument("--label", action="append", required=True)


def _label_field_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--description")
    parser.add_argument("--color")


def _add_comment(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    comment = sub.add_parser("comment", help="Manage task comments")
    comment_sub = comment.add_subparsers(dest="subcmd")

    s = comment_sub.add_parser("list")
    s.add_argument("--task", required=True)
    s.add_argument("--order", choices=["asc", "desc"])

    s = comment_sub.add_parser("add")
    s.add_argument("--task", required=True)
    s.add_argument("--message", required=True)

    s = comment_sub.add_parser("update")
    s.add_argument("--task", required=True)
    s.add_argument("--comment", required=True)
    s.add_argument("--message", required=True)

    s = comment_sub.add_parser("delete")
    s.add_argument("--task", required=True)
    s.add_argument("--comment", required=True)
    s.add_argument("--yes", action="store_true")


def _add_notification(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    notification = sub.add_parser("notification", help="Read due/reminder notifications")
    notif_sub = notification.add_subparsers(dest="subcmd")

    s = notif_sub.add_parser("list")
    s.add_argument("--kind", required=True, choices=["due", "reminder", "overdue"])
    s.add_argument("--unread", action="store_true")

    s = notif_sub.add_parser("read")
    s.add_argument("id", type=int)

    s = notif_sub.add_parser("read-all")
    s.add_argument("--kind", required=True, choices=["due", "reminder", "overdue"])


def _add_view(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    view = sub.add_parser("view", help="Manage project views")
    view_sub = view.add_subparsers(dest="subcmd")

    s = view_sub.add_parser("list")
    s.add_argument("--project", required=True)

    s = view_sub.add_parser("show")
    s.add_argument("view")
    s.add_argument("--project", required=True)

    s = view_sub.add_parser("create")
    s.add_argument("--project", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--kind", required=True, choices=["list", "table", "kanban", "gantt"])
    s.add_argument("--filter")

    s = view_sub.add_parser("update")
    s.add_argument("view")
    s.add_argument("--project", required=True)
    s.add_argument("--title")
    s.add_argument("--kind", choices=["list", "table", "kanban", "gantt"])
    filter_group = s.add_mutually_exclusive_group()
    filter_group.add_argument("--filter")
    filter_group.add_argument("--clear-filter", action="store_true")
    s.add_argument("--bucket-mode", choices=["none", "manual", "filter"])
    s.add_argument("--bucket-filter", action="append")

    s = view_sub.add_parser("delete")
    s.add_argument("view")
    s.add_argument("--project", required=True)
    s.add_argument("--yes", action="store_true")


def _add_template(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    template = sub.add_parser("template", help="Render task templates")
    template_sub = template.add_subparsers(dest="subcmd")

    s = template_sub.add_parser("list")
    _template_common_args(s)

    s = template_sub.add_parser("show")
    s.add_argument("template")
    _template_common_args(s)

    s = template_sub.add_parser("render")
    s.add_argument("template")
    s.add_argument("--context", required=True, help="JSON context file, or '-' for stdin")
    _template_common_args(s)

    s = template_sub.add_parser("validate")
    s.add_argument("template", nargs="?")
    s.add_argument("--all", action="store_true", help="Validate all template directories")
    _template_common_args(s)

    s = template_sub.add_parser("required")
    s.add_argument("template")
    _template_common_args(s)


def _template_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--template-dir", help="Template directory (default: XDG config path)")


def _add_bucket(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    bucket = sub.add_parser("bucket", help="Manage manual kanban buckets")
    bucket_sub = bucket.add_subparsers(dest="subcmd")

    s = bucket_sub.add_parser("list")
    _bucket_context_args(s)

    s = bucket_sub.add_parser("create")
    _bucket_context_args(s)
    s.add_argument("--title", required=True)
    s.add_argument("--limit", type=int)

    s = bucket_sub.add_parser("update")
    s.add_argument("bucket")
    _bucket_context_args(s)
    s.add_argument("--title")
    s.add_argument("--limit", type=int)

    s = bucket_sub.add_parser("move-task")
    _bucket_context_args(s)
    s.add_argument("--task", required=True)
    s.add_argument("--bucket", required=True)

    s = bucket_sub.add_parser("delete")
    s.add_argument("bucket")
    _bucket_context_args(s)
    s.add_argument("--yes", action="store_true")


def _bucket_context_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--view", required=True)


_HANDLERS: dict[tuple[str, str | None], Handler] = {
    ("setup", "labels"): cmd_setup_labels,
    ("project", "list"): cmd_project_list,
    ("project", "show"): cmd_project_show,
    ("project", "create"): cmd_project_create,
    ("project", "update"): cmd_project_update,
    ("project", "archive"): cmd_project_update,
    ("project", "unarchive"): cmd_project_update,
    ("project", "delete"): cmd_project_delete,
    ("task", "list"): cmd_task_list,
    ("task", "show"): cmd_task_show,
    ("task", "create"): cmd_task_create,
    ("task", "update"): cmd_task_update,
    ("task", "move"): cmd_task_move,
    ("task", "transition"): cmd_task_transition,
    ("task", "complete"): cmd_task_complete,
    ("task", "reopen"): cmd_task_reopen,
    ("task", "duplicate"): cmd_task_duplicate,
    ("task", "delete"): cmd_task_delete,
    ("attachment", "list"): cmd_attachment_list,
    ("attachment", "upload"): cmd_attachment_upload,
    ("attachment", "download"): cmd_attachment_download,
    ("attachment", "delete"): cmd_attachment_delete,
    ("relation", "list"): cmd_relation_list,
    ("relation", "add"): cmd_relation_add,
    ("relation", "remove"): cmd_relation_remove,
    ("label", "list"): cmd_label_list,
    ("label", "show"): cmd_label_show,
    ("label", "create"): cmd_label_create,
    ("label", "update"): cmd_label_update,
    ("label", "delete"): cmd_label_delete,
    ("label", "add-to-task"): cmd_label_add_to_task,
    ("label", "remove-from-task"): cmd_label_remove_from_task,
    ("label", "replace-on-task"): cmd_label_replace_on_task,
    ("comment", "list"): cmd_comment_list,
    ("comment", "add"): cmd_comment_add,
    ("comment", "update"): cmd_comment_update,
    ("comment", "delete"): cmd_comment_delete,
    ("notification", "list"): cmd_notification_list,
    ("notification", "read"): cmd_notification_read,
    ("notification", "read-all"): cmd_notification_read_all,
    ("view", "list"): cmd_view_list,
    ("view", "show"): cmd_view_show,
    ("view", "create"): cmd_view_create,
    ("view", "update"): cmd_view_update,
    ("view", "delete"): cmd_view_delete,
    ("bucket", "list"): cmd_bucket_list,
    ("bucket", "create"): cmd_bucket_create,
    ("bucket", "update"): cmd_bucket_update,
    ("bucket", "move-task"): cmd_bucket_move_task,
    ("bucket", "delete"): cmd_bucket_delete,
    ("template", "list"): cmd_template_list,
    ("template", "show"): cmd_template_show,
    ("template", "render"): cmd_template_render,
    ("template", "validate"): cmd_template_validate,
    ("template", "required"): cmd_template_required,
}


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    ns = parser.parse_args(argv)
    if not ns.command:
        parser.print_help()
        sys.exit(0)

    try:
        if ns.command == "bootstrap":
            _cmd_bootstrap(ns)
            return
        key = (ns.command, getattr(ns, "subcmd", None))
        handler = _HANDLERS.get(key)
        if handler is None:
            parser.parse_args([ns.command, "--help"])
            return
        client = None if ns.command == "template" else _make_client()
        handler(client, ns)
    except CLIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
