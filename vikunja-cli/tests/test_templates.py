from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from vikunja_cli import templates
from vikunja_cli.main import main

SOURCE_KINDS = [
    "url",
    "webmail",
    "file",
    "attached",
    "notmuch",
    "maildir",
    "issue",
    "pr",
    "ci",
    "docs",
    "other",
]


def schema_for(
    name: str,
    *,
    description: str | None = None,
    checklist_min: int = 1,
    checklist_max: int = 5,
    checklist_description: str = "Progress milestones.",
    proof_required: bool = False,
    proof_description: str = "Evidence to save.",
    note_hints: list[str] | None = None,
) -> dict[str, Any]:
    required = ["summary", "checklist"]
    if proof_required:
        required.append("proof")
    proof: dict[str, Any] = {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": 3,
        "description": proof_description,
    }
    if proof_required:
        proof["minItems"] = 1
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "title": f"{name} context",
        "description": description or f"{name} context",
        "additionalProperties": False,
        "required": required,
        "properties": {
            "summary": {"type": "string", "minLength": 1},
            "checklist": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": checklist_min,
                "maxItems": checklist_max,
                "description": checklist_description,
            },
            "notes": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "proof": proof,
            "sources": {
                "type": "array",
                "items": {"$ref": "#/$defs/Source"},
                "maxItems": 5,
            },
        },
        "$defs": {
            "SourceKind": {"type": "string", "enum": SOURCE_KINDS},
            "Source": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "locator"],
                "properties": {
                    "kind": {"$ref": "#/$defs/SourceKind"},
                    "locator": {"type": "string", "minLength": 1},
                    "title": {"type": "string"},
                },
            },
        },
        "x-note_hints": note_hints or ["why", "next step"],
    }


def write_template(
    root: Path,
    name: str,
    *,
    checklist_min: int = 1,
    checklist_max: int = 5,
    priority: int = 4,
    labels: list[str] | None = None,
    description: str | None = None,
    proof_required: bool = False,
    proof_description: str = "Evidence to save.",
    note_hints: list[str] | None = None,
    invalid_extra: dict[str, Any] | None = None,
) -> Path:
    path = root / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "name": name,
        "description": description or f"{name} context",
        "defaults": {"priority": priority, "labels": labels or [f"type:{name}", "state:someday"]},
        "schema": schema_for(
            name,
            description=description,
            checklist_min=checklist_min,
            checklist_max=checklist_max,
            proof_required=proof_required,
            proof_description=proof_description,
            note_hints=note_hints,
        ),
        "attachment_expectations": [proof_description] if proof_description else [],
    }
    if invalid_extra:
        data.update(invalid_extra)
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n\n# Template\n")
    return path


def read_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text()
    frontmatter = text.split("---", 2)[1]
    data = yaml.safe_load(frontmatter)
    assert isinstance(data, dict)
    return data


def write_frontmatter(path: Path, data: dict[str, Any]) -> None:
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n\n# Template\n")


def test_render_template_uses_fixed_description_layout(tmp_path: Path) -> None:
    write_template(tmp_path, "backlog")

    rendered = templates.render_template(
        "backlog",
        {
            "summary": "Prototype thing",
            "checklist": ["Decide scope"],
            "notes": ["Keep native metadata out of description"],
            "proof": ["Decision recorded"],
            "sources": [
                {
                    "kind": "webmail",
                    "locator": "https://mail.mulatta.io/ko?email=boiqaaalse",
                    "title": "Ground News",
                }
            ],
        },
        template_dir=tmp_path,
    )

    assert rendered["missing_required"] == []
    assert rendered["defaults"] == {"labels": ["type:backlog", "state:someday"], "priority": 4}
    assert rendered["description"] == (
        "## Summary\n"
        "Prototype thing\n\n"
        "## Checklist\n"
        "- [ ] Decide scope\n\n"
        "## Notes\n"
        "- Keep native metadata out of description\n\n"
        "## Proof\n"
        "- Decision recorded\n\n"
        "## Sources\n"
        "- webmail: https://mail.mulatta.io/ko?email=boiqaaalse — Ground News\n"
    )


def test_render_template_reports_missing_required_fields(tmp_path: Path) -> None:
    write_template(tmp_path, "backlog")

    rendered = templates.render_template("backlog", {"checklist": []}, template_dir=tmp_path)

    assert rendered["missing_required"] == ["summary", "checklist (minItems 1)"]


def test_render_template_reports_template_minimums(tmp_path: Path) -> None:
    write_template(tmp_path, "submission", checklist_min=3, proof_required=True)

    rendered = templates.render_template(
        "submission",
        {"summary": "Submit packet", "checklist": ["Draft"]},
        template_dir=tmp_path,
    )

    assert rendered["missing_required"] == ["checklist (minItems 3)", "proof (minItems 1)"]


def test_render_template_rejects_invalid_source_kind_when_required_fields_present(
    tmp_path: Path,
) -> None:
    write_template(tmp_path, "backlog")

    with pytest.raises(Exception) as excinfo:
        templates.render_template(
            "backlog",
            {
                "summary": "Check source",
                "checklist": ["Verify"],
                "sources": [{"kind": "email", "locator": "bare-message-id"}],
            },
            template_dir=tmp_path,
        )

    assert "template context failed validation" in str(excinfo.value)
    assert "sources.0.kind" in str(excinfo.value)


def test_render_template_exposes_vikunja_html_description(tmp_path: Path) -> None:
    write_template(tmp_path, "backlog")

    rendered = templates.render_template(
        "backlog",
        {
            "summary": "Prototype <thing>",
            "checklist": ["첫 단계", "둘째 `code`"],
            "sources": [{"kind": "url", "locator": "https://example.test/thread"}],
        },
        template_dir=tmp_path,
    )

    assert rendered["description_html"] == (
        "<h2>Summary</h2>\n"
        "<p>Prototype &lt;thing&gt;</p>\n"
        "<h2>Checklist</h2>\n"
        '<ul data-type="taskList">\n'
        '<li data-type="taskItem" data-checked="false"><p>첫 단계</p></li>\n'
        '<li data-type="taskItem" data-checked="false"><p>둘째 <code>code</code></p></li>\n'
        "</ul>\n"
        "<h2>Sources</h2>\n"
        "<ul>\n"
        '<li><p>url: <a target="_blank" rel="noopener noreferrer nofollow" '
        'href="https://example.test/thread">https://example.test/thread</a></p></li>\n'
        "</ul>\n"
    )


def test_template_render_command_does_not_require_vikunja_credentials(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_template(tmp_path, "backlog")
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"summary": "CLI render", "checklist": ["one"]}))

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
    assert data["description"] == "## Summary\nCLI render\n\n## Checklist\n- [ ] one\n"


def test_validate_template_accepts_valid_template(tmp_path: Path) -> None:
    write_template(tmp_path, "backlog")

    record = templates.validate_template("backlog", template_dir=tmp_path)

    assert record["ok"] is True
    assert record["errors"] == []


def test_validate_template_rejects_invalid_template_yaml(tmp_path: Path) -> None:
    path = write_template(tmp_path, "backlog")
    path.write_text("---\nname: [\n---\n")

    record = templates.validate_template("backlog", template_dir=tmp_path)

    assert record["ok"] is False
    assert any("invalid YAML in backlog.md" in item for item in record["errors"])


def test_validate_template_rejects_invalid_template_spec(tmp_path: Path) -> None:
    path = write_template(tmp_path, "backlog")
    data = read_frontmatter(path)
    data["defaults"]["priority"] = "high"
    write_frontmatter(path, data)

    record = templates.validate_template("backlog", template_dir=tmp_path)

    assert record["ok"] is False
    assert any("defaults.priority" in item for item in record["errors"])


def test_validate_template_rejects_name_mismatch(tmp_path: Path) -> None:
    path = write_template(tmp_path, "backlog")
    data = read_frontmatter(path)
    data["name"] = "other"
    write_frontmatter(path, data)

    record = templates.validate_template("backlog", template_dir=tmp_path)

    assert record["ok"] is False
    assert "template name 'other' does not match file name 'backlog'" in record["errors"]


def test_validate_template_rejects_missing_template_file_for_explicit_template(
    tmp_path: Path,
) -> None:
    record = templates.validate_template("broken", template_dir=tmp_path)

    assert record["ok"] is False
    assert "missing broken.md" in record["errors"]


def test_default_template_lookup_uses_xdg_data_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template_dir = tmp_path / "data" / "vikunja-cli" / "templates"
    write_template(template_dir, "backlog")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_DATA_DIRS", "")
    monkeypatch.delenv("VIKUNJA_TEMPLATE_DIR", raising=False)

    assert templates.list_templates() == ["backlog"]


def test_validate_all_reports_all_template_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_template(tmp_path, "good")
    bad = write_template(tmp_path, "bad")
    data = read_frontmatter(bad)
    data["schema"]["properties"]["checklist"]["minItems"] = 4
    data["schema"]["properties"]["checklist"]["maxItems"] = 2
    write_frontmatter(bad, data)

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
    write_template(
        tmp_path,
        "submission",
        priority=5,
        labels=["type:submission", "state:next"],
        checklist_min=3,
        proof_required=True,
        proof_description="Receipt or confirmation",
    )

    required = templates.template_required("submission", template_dir=tmp_path)

    assert required["template"] == "submission"
    assert required["required"] == ["summary", "checklist", "proof"]
    assert required["required_any"] == []
    assert required["optional"] == ["notes", "sources"]
    assert required["attachment_expectations"] == ["Receipt or confirmation"]
    assert required["defaults"] == {"priority": 5, "labels": ["type:submission", "state:next"]}


def test_template_schema_reads_context_schema_and_types_from_markdown_yaml(
    tmp_path: Path,
) -> None:
    write_template(
        tmp_path,
        "submission",
        description="External form/document/package submission.",
        checklist_min=3,
        checklist_max=5,
        proof_required=True,
        proof_description="Receipt, confirmation email, or screenshot.",
        note_hints=["channel", "format"],
    )

    result = templates.template_schema("submission", template_dir=tmp_path)

    schema = result["schema"]
    assert schema["title"] == "submission context"
    assert schema["description"] == "External form/document/package submission."
    assert schema["required"] == ["summary", "checklist", "proof"]
    assert schema["properties"]["checklist"]["minItems"] == 3
    assert schema["properties"]["checklist"]["maxItems"] == 5
    assert schema["properties"]["proof"]["minItems"] == 1
    assert schema["x-note_hints"] == ["channel", "format"]
    assert "webmail" in schema["$defs"]["SourceKind"]["enum"]
    assert "locator" in schema["$defs"]["Source"]["properties"]
    assert "ref" not in schema["$defs"]["Source"]["properties"]


def test_template_schema_command_outputs_schema(
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
    assert data["attachment_expectations"] == ["Evidence to save."]


def test_template_required_command_outputs_defaults(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_template(tmp_path, "submission")

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
    assert data["defaults"] == {"priority": 4, "labels": ["type:submission", "state:someday"]}
