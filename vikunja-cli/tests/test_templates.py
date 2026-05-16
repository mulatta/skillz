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
{% if sources %}
## Sources
{% for source in sources %}- {{ source.kind }}: {{ source.ref }}
{% endfor %}{% endif %}
## Summary
{{ summary }}
{% if checklist %}
## Checklist
{% for item in checklist %}- [ ] {{ item }}
{% endfor %}{% endif %}
<!-- removed -->
"""
    )
    (template_root / "defaults.json").write_text(
        json.dumps({"labels": [f"type:{name}", "state:someday"], "priority": 4})
    )
    (template_root / "schema.json").write_text(
        json.dumps(
            {
                "title": f"{name} context",
                "required": ["summary", "sources"],
                "properties": {
                    "sources": {"minItems": 1},
                    "checklist": {"minItems": 1, "maxItems": 5},
                },
                "x-attachment_expectations": ["source docs or issue"],
            }
        )
    )
    return template_root


def test_render_template_prunes_missing_fields_and_strips_comments(tmp_path: Path) -> None:
    write_template(tmp_path, "backlog")

    rendered = templates.render_template(
        "backlog",
        {
            "summary": "Prototype thing",
            "sources": [{"kind": "slack", "ref": "https://slack/thread"}],
        },
        template_dir=tmp_path,
    )

    assert rendered["missing_required"] == []
    assert rendered["defaults"] == {"labels": ["type:backlog", "state:someday"], "priority": 4}
    assert rendered["description"] == (
        "## Sources\n- slack: https://slack/thread\n\n## Summary\nPrototype thing\n"
    )
    assert "removed" not in rendered["description"]


def test_render_template_reports_missing_required_fields(tmp_path: Path) -> None:
    write_template(tmp_path, "backlog")

    rendered = templates.render_template("backlog", {"sources": []}, template_dir=tmp_path)

    assert rendered["missing_required"] == ["summary", "sources (minItems 1)"]


def test_render_template_exposes_vikunja_html_description(tmp_path: Path) -> None:
    write_template(tmp_path, "backlog")

    rendered = templates.render_template(
        "backlog",
        {
            "summary": "Prototype <thing>",
            "sources": [{"kind": "slack", "ref": "https://slack.example/thread"}],
            "checklist": ["첫 단계", "둘째 `code`"],
        },
        template_dir=tmp_path,
    )

    assert rendered["description_html"] == (
        "<h2>Sources</h2>\n"
        "<ul>\n"
        '<li><p>slack: <a target="_blank" rel="noopener noreferrer nofollow" '
        'href="https://slack.example/thread">https://slack.example/thread</a></p></li>\n'
        "</ul>\n"
        "<h2>Summary</h2>\n"
        "<p>Prototype &lt;thing&gt;</p>\n"
        "<h2>Checklist</h2>\n"
        '<ul data-type="taskList">\n'
        '<li data-type="taskItem" data-checked="false"><p>첫 단계</p></li>\n'
        '<li data-type="taskItem" data-checked="false"><p>둘째 <code>code</code></p></li>\n'
        "</ul>\n"
    )


def test_template_render_command_does_not_require_vikunja_credentials(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_template(tmp_path, "backlog")
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps({"summary": "CLI render", "sources": [{"kind": "url", "ref": "url"}]})
    )

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
    assert data["description"] == "## Sources\n- url: url\n\n## Summary\nCLI render\n"


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
    (template_root / "schema.json").write_text(json.dumps({"required": "summary"}))

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
    (broken / "schema.json").write_text(json.dumps({"properties": []}))

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
                "required": ["summary", "sources"],
                "properties": {"notes": {"type": "array"}},
                "x-attachment_expectations": ["patch file"],
            }
        )
    )

    data = templates.template_required("submission", template_dir=tmp_path)

    assert data == {
        "template": "submission",
        "required": ["summary", "sources"],
        "required_any": [],
        "optional": [
            "facts",
            "requirements",
            "checklist",
            "relations",
            "questions",
            "attachments",
            "proof",
            "notes",
            "template",
        ],
        "attachment_expectations": ["patch file"],
        "defaults": {"priority": 4, "labels": ["type:submission", "state:next"]},
    }


def test_template_required_uses_empty_lists_for_missing_schema_keys(
    tmp_path: Path,
) -> None:
    template_root = write_template(tmp_path, "submission")
    (template_root / "schema.json").write_text(json.dumps({"required": ["summary"]}))

    data = templates.template_required("submission", template_dir=tmp_path)

    assert data["required"] == ["summary"]
    assert data["required_any"] == []
    assert data["optional"] == [
        "sources",
        "facts",
        "requirements",
        "checklist",
        "relations",
        "questions",
        "attachments",
        "proof",
        "notes",
        "template",
    ]
    assert data["attachment_expectations"] == []


def test_template_schema_merges_common_schema_and_template_patch(tmp_path: Path) -> None:
    (tmp_path / "common.schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["summary"],
                "properties": {
                    "summary": {"type": "string", "description": "Common summary"},
                    "sources": {"type": "array", "items": {"type": "object"}},
                },
            }
        )
    )
    template_root = write_template(tmp_path, "submission")
    (template_root / "schema.json").write_text(
        json.dumps(
            {
                "required": ["sources"],
                "properties": {
                    "sources": {"minItems": 1, "description": "Submission sources"},
                    "template": {
                        "type": "object",
                        "properties": {
                            "submission": {
                                "type": "object",
                                "required": ["deadline"],
                                "properties": {"deadline": {"type": "string"}},
                            }
                        },
                    },
                },
            }
        )
    )

    data = templates.template_schema("submission", template_dir=tmp_path)

    schema = data["schema"]
    assert schema["required"] == ["summary", "sources"]
    assert schema["properties"]["summary"]["description"] == "Common summary"
    assert schema["properties"]["sources"]["type"] == "array"
    assert schema["properties"]["sources"]["minItems"] == 1
    assert schema["properties"]["sources"]["description"] == "Submission sources"
    assert schema["properties"]["template"]["properties"]["submission"]["required"] == ["deadline"]


def test_template_schema_command_outputs_merged_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_template(tmp_path, "submission")

    main(
        [
            "-j",
            "template",
            "schema",
            "submission",
            "--template-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["template"] == "submission"
    assert data["schema"]["type"] == "object"
    assert "summary" in data["schema"]["properties"]
    assert data["attachment_expectations"] == ["source docs or issue"]


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
