from __future__ import annotations

import json
from pathlib import Path

import pytest

from vikunja_cli import templates
from vikunja_cli.main import main


def write_template(root: Path, name: str) -> Path:
    template_root = root / name
    template_root.mkdir(parents=True)
    (template_root / "template.md.njk").write_text(
        """{# removed #}
{% if sources.slack_thread %}
## Sources
- Slack thread: {{ sources.slack_thread }}
{% endif %}
## Goal
{{ goal }}
{% if optional %}
## Optional
{{ optional }}
{% endif %}
<!-- removed -->
"""
    )
    (template_root / "defaults.json").write_text(
        json.dumps({"labels": [f"type:{name}", "state:someday"], "priority": 4})
    )
    (template_root / "schema.json").write_text(
        json.dumps(
            {
                "required": ["goal"],
                "required_any": [["sources.slack_thread", "sources.email_thread"]],
            }
        )
    )
    return template_root


def test_render_template_prunes_missing_fields_and_strips_comments(tmp_path: Path) -> None:
    write_template(tmp_path, "backlog")

    rendered = templates.render_template(
        "backlog",
        {"goal": "Prototype thing", "sources": {"slack_thread": "https://slack/thread"}},
        template_dir=tmp_path,
    )

    assert rendered["missing_required"] == []
    assert rendered["defaults"] == {"labels": ["type:backlog", "state:someday"], "priority": 4}
    assert rendered["description"] == (
        "## Sources\n- Slack thread: https://slack/thread\n\n## Goal\nPrototype thing\n"
    )
    assert "Optional" not in rendered["description"]
    assert "removed" not in rendered["description"]


def test_render_template_reports_missing_required_fields(tmp_path: Path) -> None:
    write_template(tmp_path, "backlog")

    rendered = templates.render_template("backlog", {"sources": {}}, template_dir=tmp_path)

    assert rendered["missing_required"] == [
        "goal",
        "one of: sources.slack_thread, sources.email_thread",
    ]


def test_template_render_command_does_not_require_vikunja_credentials(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_template(tmp_path, "backlog")
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"goal": "CLI render", "sources": {"slack_thread": "url"}}))

    main(
        [
            "-j",
            "template",
            "render",
            "backlog",
            "--template-dir",
            str(tmp_path),
            "--context",
            str(context),
        ]
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["description"] == "## Sources\n- Slack thread: url\n\n## Goal\nCLI render\n"


def test_validate_template_accepts_valid_template(tmp_path: Path) -> None:
    write_template(tmp_path, "backlog")

    record = templates.validate_template("backlog", template_dir=tmp_path)

    assert record["ok"] is True
    assert record["errors"] == []


def test_validate_template_rejects_invalid_jinja_syntax(tmp_path: Path) -> None:
    template_root = write_template(tmp_path, "backlog")
    (template_root / "template.md.njk").write_text("{% if goal %}")

    record = templates.validate_template("backlog", template_dir=tmp_path)

    assert record["ok"] is False
    assert any("invalid Jinja syntax" in item for item in record["errors"])


def test_validate_template_rejects_invalid_schema_json(tmp_path: Path) -> None:
    template_root = write_template(tmp_path, "backlog")
    (template_root / "schema.json").write_text("{")

    record = templates.validate_template("backlog", template_dir=tmp_path)

    assert record["ok"] is False
    assert any("invalid JSON in schema.json" in item for item in record["errors"])


def test_validate_template_rejects_invalid_schema_field_type(tmp_path: Path) -> None:
    template_root = write_template(tmp_path, "backlog")
    (template_root / "schema.json").write_text(json.dumps({"required": "goal"}))

    record = templates.validate_template("backlog", template_dir=tmp_path)

    assert record["ok"] is False
    assert "schema.json field 'required' must be a list of strings" in record["errors"]


def test_validate_template_rejects_invalid_defaults_field_type(tmp_path: Path) -> None:
    template_root = write_template(tmp_path, "backlog")
    (template_root / "defaults.json").write_text(json.dumps({"priority": "high"}))

    record = templates.validate_template("backlog", template_dir=tmp_path)

    assert record["ok"] is False
    assert "defaults.json field 'priority' must be an integer" in record["errors"]


def test_validate_template_rejects_unsupported_default_shortcuts(tmp_path: Path) -> None:
    template_root = write_template(tmp_path, "backlog")
    (template_root / "defaults.json").write_text(json.dumps({"type": "backlog", "label": "next"}))

    record = templates.validate_template("backlog", template_dir=tmp_path)

    assert record["ok"] is False
    assert record["errors"] == [
        "defaults.json field 'type' is unsupported; use 'labels' entries",
        "defaults.json field 'label' is unsupported; use 'labels' entries",
    ]
    assert record["warnings"] == []


def test_validate_template_rejects_missing_template_file_for_explicit_template(
    tmp_path: Path,
) -> None:
    (tmp_path / "broken").mkdir()

    record = templates.validate_template("broken", template_dir=tmp_path)

    assert record["ok"] is False
    assert "missing template.md.njk" in record["errors"]


def test_validate_all_reports_all_template_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_template(tmp_path, "good")
    broken = write_template(tmp_path, "bad")
    (broken / "schema.json").write_text(json.dumps({"required_any": ["goal"]}))

    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "-j",
                "template",
                "validate",
                "--all",
                "--template-dir",
                str(tmp_path),
            ]
        )

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert [item["template"] for item in data] == ["bad", "good"]
    assert data[0]["ok"] is False
    assert data[1]["ok"] is True


def test_template_validate_command_does_not_require_vikunja_credentials(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_template(tmp_path, "backlog")

    main(
        [
            "-j",
            "template",
            "validate",
            "backlog",
            "--template-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data[0]["template"] == "backlog"
    assert data[0]["ok"] is True


def test_template_required_outputs_schema_fields(tmp_path: Path) -> None:
    template_root = write_template(tmp_path, "submission")
    (template_root / "defaults.json").write_text(
        json.dumps({"priority": 4, "labels": ["type:submission", "state:next"]})
    )
    (template_root / "schema.json").write_text(
        json.dumps(
            {
                "required": ["goal"],
                "required_any": [["sources.slack_thread", "sources.email_thread"]],
                "optional": ["notes"],
                "attachment_expectations": ["patch file"],
            }
        )
    )

    data = templates.template_required("submission", template_dir=tmp_path)

    assert data == {
        "template": "submission",
        "required": ["goal"],
        "required_any": [["sources.slack_thread", "sources.email_thread"]],
        "optional": ["notes"],
        "attachment_expectations": ["patch file"],
        "defaults": {"priority": 4, "labels": ["type:submission", "state:next"]},
    }


def test_template_required_uses_empty_lists_for_missing_schema_keys(
    tmp_path: Path,
) -> None:
    template_root = write_template(tmp_path, "submission")
    (template_root / "schema.json").write_text(json.dumps({"required": ["goal"]}))

    data = templates.template_required("submission", template_dir=tmp_path)

    assert data["required"] == ["goal"]
    assert data["required_any"] == []
    assert data["optional"] == []
    assert data["attachment_expectations"] == []


def test_template_required_command_outputs_defaults(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    template_root = write_template(tmp_path, "submission")
    (template_root / "defaults.json").write_text(
        json.dumps({"priority": 5, "labels": ["type:submission"]})
    )

    main(
        [
            "-j",
            "template",
            "required",
            "submission",
            "--template-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["defaults"] == {"priority": 5, "labels": ["type:submission"]}
