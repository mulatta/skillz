"""Task template rendering for vikunja-cli."""

from __future__ import annotations

import html
import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, cast

from jinja2 import (
    ChainableUndefined,
    Environment,
    FileSystemLoader,
    TemplateError,
    TemplateSyntaxError,
    UndefinedError,
)

from vikunja_cli.errors import InputError

HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
URL_RE = re.compile(r"https?://[^\s<>()]+[^\s<>().,;:!?]")
SCHEMA_LIST_FIELDS = (
    "required",
    "optional",
    "attachment_expectations",
    "x-attachment_expectations",
)
COMMON_SCHEMA_NAME = "common.schema.json"

COMMON_CONTEXT_SCHEMA: dict[str, Any] = {
    "title": "Vikunja template context",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {
            "type": "string",
            "description": "Concise task outcome or goal.",
        },
        "sources": {
            "type": "array",
            "description": "Source links/files/messages that justify the task.",
            "items": {"$ref": "#/$defs/source"},
        },
        "facts": {
            "type": "array",
            "description": "Extracted facts needed to execute the task.",
            "items": {"$ref": "#/$defs/textItem"},
        },
        "requirements": {
            "type": "array",
            "description": "Obligations, constraints, or acceptance requirements.",
            "items": {"$ref": "#/$defs/textItem"},
        },
        "checklist": {
            "type": "array",
            "description": "Vikunja progress milestones; each item renders as a checkbox.",
            "items": {"$ref": "#/$defs/textItem"},
            "maxItems": 5,
        },
        "relations": {
            "type": "array",
            "description": "Task relations to create after task creation.",
            "items": {"$ref": "#/$defs/relation"},
        },
        "questions": {
            "type": "array",
            "description": "Open questions or unknowns that are not task relations yet.",
            "items": {"$ref": "#/$defs/textItem"},
        },
        "attachments": {
            "type": "array",
            "description": "Local files or expected files to attach to the task.",
            "items": {"$ref": "#/$defs/attachment"},
        },
        "proof": {
            "type": "array",
            "description": "Evidence expected when the task is done.",
            "items": {"$ref": "#/$defs/textItem"},
        },
        "notes": {
            "type": "array",
            "description": "Short supporting notes that do not fit other fields.",
            "items": {"$ref": "#/$defs/textItem"},
        },
        "template": {
            "type": "object",
            "description": "Template-specific fields that cannot be represented by common fields.",
            "additionalProperties": True,
        },
    },
    "$defs": {
        "textItem": {
            "oneOf": [
                {"type": "string"},
                {
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            ]
        },
        "source": {
            "type": "object",
            "required": ["kind", "ref"],
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": [
                        "url",
                        "file",
                        "email",
                        "slack",
                        "issue",
                        "pr",
                        "ci",
                        "log",
                        "docs",
                        "notice",
                        "screenshot",
                        "other",
                    ],
                },
                "ref": {"type": "string"},
                "title": {"type": "string"},
                "note": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "relation": {
            "type": "object",
            "required": ["kind", "task"],
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": [
                        "blocked",
                        "blocking",
                        "subtask",
                        "parenttask",
                        "precedes",
                        "follows",
                        "related",
                    ],
                },
                "task": {"type": "string"},
                "reason": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "attachment": {
            "oneOf": [
                {"type": "string"},
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string"},
                        "purpose": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            ]
        },
    },
}


class TemplateSchema(TypedDict, total=False):
    description: str
    required: list[str]
    required_any: list[list[str]]
    optional: list[str]
    attachment_expectations: list[str]


class TemplateValidationRecord(TypedDict):
    template: str
    ok: bool
    errors: list[str]
    warnings: list[str]


class TemplateRequiredMetadata(TypedDict):
    template: str
    required: list[str]
    required_any: list[list[str]]
    optional: list[str]
    attachment_expectations: list[str]
    defaults: dict[str, Any]


class TemplateSchemaMetadata(TypedDict):
    template: str
    schema: dict[str, Any]
    defaults: dict[str, Any]
    attachment_expectations: list[str]


@dataclass(frozen=True)
class LoadedTemplate:
    name: str
    root: Path
    template_path: Path
    defaults: dict[str, Any]
    schema: TemplateSchema


def default_template_dir() -> Path:
    override = os.environ.get("VIKUNJA_TEMPLATE_DIR")
    if override:
        return Path(override).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "vikunja-cli" / "templates"


def list_templates(template_dir: Path | None = None) -> list[str]:
    base = (template_dir or default_template_dir()).expanduser()
    if not base.exists():
        return []
    result: list[str] = []
    for item in base.iterdir():
        if not item.is_dir():
            continue
        if (item / "template.md.njk").exists():
            result.append(item.name)
    return sorted(result)


def validate_template(
    name: str,
    *,
    template_dir: Path | None = None,
) -> TemplateValidationRecord:
    template_name = name.strip()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        safe_name, root = _resolve_template_root(name, template_dir=template_dir)
        template_name = safe_name
    except InputError as exc:
        return {
            "template": template_name,
            "ok": False,
            "errors": [str(exc)],
            "warnings": [],
        }

    template_path = root / "template.md.njk"
    if not template_path.exists():
        errors.append("missing template.md.njk")
    elif not template_path.is_file():
        errors.append("template.md.njk is not a file")
    else:
        _validate_jinja(root, errors)

    common_schema = _read_json_object_for_validation(root.parent / COMMON_SCHEMA_NAME, errors)
    schema = _read_json_object_for_validation(root / "schema.json", errors)
    defaults = _read_json_object_for_validation(root / "defaults.json", errors)
    _validate_schema_shape(common_schema, errors, source=COMMON_SCHEMA_NAME)
    _validate_schema_shape(schema, errors, source="schema.json")
    _validate_defaults_shape(defaults, errors, warnings)

    return {
        "template": template_name,
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def validate_templates(template_dir: Path | None = None) -> list[TemplateValidationRecord]:
    base = (template_dir or default_template_dir()).expanduser()
    if not base.exists():
        return []
    names = sorted(item.name for item in base.iterdir() if item.is_dir())
    return [validate_template(name, template_dir=base) for name in names]


def template_required(
    name: str,
    *,
    template_dir: Path | None = None,
) -> TemplateRequiredMetadata:
    validation = validate_template(name, template_dir=template_dir)
    if validation["errors"]:
        raise InputError("template validation failed: " + "; ".join(validation["errors"]))
    loaded = load_template(name, template_dir=template_dir)
    schema = loaded.schema
    required = _schema_required(schema)
    return {
        "template": loaded.name,
        "required": required,
        "required_any": [list(group) for group in schema.get("required_any", [])],
        "optional": _schema_optional(schema, required),
        "attachment_expectations": _schema_attachment_expectations(schema),
        "defaults": loaded.defaults,
    }


def template_schema(
    name: str,
    *,
    template_dir: Path | None = None,
) -> TemplateSchemaMetadata:
    validation = validate_template(name, template_dir=template_dir)
    if validation["errors"]:
        raise InputError("template validation failed: " + "; ".join(validation["errors"]))
    loaded = load_template(name, template_dir=template_dir)
    return {
        "template": loaded.name,
        "schema": loaded.schema,
        "defaults": loaded.defaults,
        "attachment_expectations": _schema_attachment_expectations(loaded.schema),
    }


def render_template(
    name: str,
    context: dict[str, Any],
    *,
    template_dir: Path | None = None,
) -> dict[str, Any]:
    loaded = load_template(name, template_dir=template_dir)
    env = Environment(
        loader=FileSystemLoader(str(loaded.root)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=True,
    )
    render_context = {**context, "__has": _has_map(context)}
    rendered = env.get_template("template.md.njk").render(**render_context)
    description = _clean_markdown(HTML_COMMENT_RE.sub("", rendered))
    return {
        "template": loaded.name,
        "template_path": str(loaded.template_path),
        "defaults": loaded.defaults,
        "schema": loaded.schema,
        "missing_required": missing_required(loaded.schema, context),
        "description": description,
        "description_html": markdown_to_vikunja_html(description),
    }


def load_template(name: str, *, template_dir: Path | None = None) -> LoadedTemplate:
    safe_name, root = _resolve_template_root(name, template_dir=template_dir)
    template_path = root / "template.md.njk"
    if not template_path.exists():
        raise InputError(f"template not found: {safe_name}")
    return LoadedTemplate(
        name=safe_name,
        root=root,
        template_path=template_path,
        defaults=_read_json_object(root / "defaults.json"),
        schema=cast("TemplateSchema", _load_merged_schema(root)),
    )


def missing_required(schema: TemplateSchema, context: dict[str, Any]) -> list[str]:
    missing = _missing_required_from_schema(cast("dict[str, Any]", schema), context)
    for group in schema.get("required_any", []):
        if not any(_truthy(_get_path(context, path)) for path in group):
            missing.append(f"one of: {', '.join(group)}")
    return missing


def _resolve_template_root(
    name: str,
    *,
    template_dir: Path | None = None,
) -> tuple[str, Path]:
    safe_name = _safe_template_name(name)
    base = (template_dir or default_template_dir()).expanduser().resolve()
    root = (base / safe_name).resolve()
    try:
        root.relative_to(base)
    except ValueError as exc:
        raise InputError("template path escapes template dir") from exc
    return safe_name, root


def _safe_template_name(name: str) -> str:
    trimmed = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", trimmed):
        raise InputError("template must contain only letters, numbers, '_' or '-'")
    return trimmed


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON in {path}: {exc}") from None
    if not isinstance(data, dict):
        raise InputError(f"expected JSON object in {path}")
    return data


def _load_merged_schema(root: Path) -> dict[str, Any]:
    common = _read_common_schema(root.parent)
    patch = _read_json_object(root / "schema.json")
    return _merge_schema(common, patch)


def _read_common_schema(base: Path) -> dict[str, Any]:
    path = base / COMMON_SCHEMA_NAME
    if not path.exists():
        return deepcopy(COMMON_CONTEXT_SCHEMA)
    return _read_json_object(path)


def _read_json_object_for_validation(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON in {path.name}: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{path.name} must be a JSON object")
        return {}
    return data


def _merge_schema(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    _merge_schema_into(merged, patch)
    return merged


def _merge_schema_into(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if key == "required" and isinstance(target.get(key), list) and isinstance(value, list):
            target[key] = _union_strings(target[key], value)
            continue
        if (
            key in {"allOf", "anyOf", "oneOf"}
            and isinstance(target.get(key), list)
            and isinstance(value, list)
        ):
            target[key] = [*target[key], *deepcopy(value)]
            continue
        if isinstance(target.get(key), dict) and isinstance(value, dict):
            _merge_schema_into(target[key], value)
            continue
        target[key] = deepcopy(value)


def _union_strings(left: list[Any], right: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in [*left, *right]:
        if isinstance(item, str):
            if item in seen:
                continue
            seen.add(item)
        result.append(item)
    return result


def _validate_jinja(root: Path, errors: list[str]) -> None:
    env = Environment(
        loader=FileSystemLoader(str(root)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=True,
        undefined=ChainableUndefined,
    )
    try:
        env.get_template("template.md.njk").render(__has={})
    except TemplateSyntaxError as exc:
        errors.append(f"invalid Jinja syntax in template.md.njk:{exc.lineno}: {exc.message}")
    except UndefinedError:
        pass
    except TemplateError as exc:
        errors.append(f"cannot render template.md.njk with empty context: {exc}")


def _validate_schema_shape(
    schema: dict[str, Any], errors: list[str], *, source: str = "schema.json"
) -> None:
    _validate_schema_node(schema, errors, source=source, path="")


def _validate_schema_node(
    schema: dict[str, Any], errors: list[str], *, source: str, path: str
) -> None:
    prefix = f"{source} field '{path}." if path else f"{source} field '"
    for field in SCHEMA_LIST_FIELDS:
        if field not in schema:
            continue
        if not _is_list_of_strings(schema[field]):
            errors.append(f"{prefix}{field}' must be a list of strings")

    if "required_any" in schema:
        groups = schema["required_any"]
        if not isinstance(groups, list) or any(not _is_list_of_strings(group) for group in groups):
            errors.append(f"{prefix}required_any' must be a list of lists of strings")

    if "properties" in schema and not isinstance(schema["properties"], dict):
        errors.append(f"{prefix}properties' must be an object")
        return

    if "minItems" in schema and (
        not isinstance(schema["minItems"], int) or isinstance(schema["minItems"], bool)
    ):
        errors.append(f"{prefix}minItems' must be an integer")
    if "maxItems" in schema and (
        not isinstance(schema["maxItems"], int) or isinstance(schema["maxItems"], bool)
    ):
        errors.append(f"{prefix}maxItems' must be an integer")

    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for key, value in properties.items():
            if not isinstance(value, dict):
                errors.append(f"{prefix}properties.{key}' must be an object")
                continue
            child_path = f"{path}.properties.{key}" if path else f"properties.{key}"
            _validate_schema_node(value, errors, source=source, path=child_path)


def _validate_defaults_shape(
    defaults: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    if "priority" in defaults and (
        not isinstance(defaults["priority"], int) or isinstance(defaults["priority"], bool)
    ):
        errors.append("defaults.json field 'priority' must be an integer")

    if "labels" in defaults and not _is_list_of_strings(defaults["labels"]):
        errors.append("defaults.json field 'labels' must be a list of strings")

    for field in ("type", "label"):
        if field in defaults:
            errors.append(f"defaults.json field '{field}' is unsupported; use 'labels' entries")


def _schema_required(schema: dict[str, Any]) -> list[str]:
    required = schema.get("required", [])
    return list(required) if _is_list_of_strings(required) else []


def _schema_optional(schema: dict[str, Any], required: list[str]) -> list[str]:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return []
    required_set = set(required)
    return [key for key in properties if key not in required_set]


def _schema_attachment_expectations(schema: dict[str, Any]) -> list[str]:
    value = schema.get("x-attachment_expectations", schema.get("attachment_expectations", []))
    return list(value) if _is_list_of_strings(value) else []


def _is_list_of_strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _has_map(context: dict[str, Any]) -> dict[str, bool]:
    return {key: _truthy(value) for key, value in context.items()}


def _missing_required_from_schema(
    schema: dict[str, Any], value: Any, *, path: str = ""
) -> list[str]:
    missing: list[str] = []
    if not isinstance(schema, dict):
        return missing

    required = schema.get("required", [])
    properties = schema.get("properties", {})
    if _is_list_of_strings(required):
        for key in required:
            child_path = f"{path}.{key}" if path else key
            child_value = value.get(key) if isinstance(value, dict) else None
            if (
                not isinstance(value, dict)
                or key not in value
                or _is_blank_required_value(child_value)
            ):
                missing.append(child_path)

    if isinstance(properties, dict) and isinstance(value, dict):
        for key, child_schema in properties.items():
            if not isinstance(child_schema, dict) or key not in value:
                continue
            child_path = f"{path}.{key}" if path else key
            child_value = value[key]
            missing.extend(
                _missing_required_from_schema(child_schema, child_value, path=child_path)
            )

            min_items = child_schema.get("minItems")
            if isinstance(min_items, int) and not isinstance(min_items, bool):
                count = len(child_value) if isinstance(child_value, list) else 0
                if count < min_items:
                    missing.append(f"{child_path} (minItems {min_items})")

    return _dedupe(missing)


def _is_blank_required_value(value: Any) -> bool:
    if value is None or value is False:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _get_path(context: dict[str, Any], path: str) -> Any:
    value: Any = context
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _truthy(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_truthy(item) for item in value)
    if isinstance(value, dict):
        return any(_truthy(item) for item in value.values())
    return True


def markdown_to_vikunja_html(value: str) -> str:
    """Convert template Markdown subset to TipTap HTML stored by Vikunja descriptions."""
    lines = [line.rstrip() for line in value.splitlines()]
    output: list[str] = []
    list_kind: str | None = None

    def close_list() -> None:
        nonlocal list_kind
        if list_kind is None:
            return
        output.append("</ul>")
        list_kind = None

    def open_list(kind: str) -> None:
        nonlocal list_kind
        if list_kind == kind:
            return
        close_list()
        if kind == "task":
            output.append('<ul data-type="taskList">')
        else:
            output.append("<ul>")
        list_kind = kind

    for line in lines:
        if not line.strip():
            close_list()
            continue

        heading = re.fullmatch(r"(#{1,6})\s+(.+)", line)
        if heading:
            close_list()
            level = len(heading.group(1))
            output.append(f"<h{level}>{_inline_markdown_to_html(heading.group(2))}</h{level}>")
            continue

        task_item = re.fullmatch(r"\s*-\s+\[([ xX])\]\s+(.+)", line)
        if task_item:
            open_list("task")
            checked = "true" if task_item.group(1).lower() == "x" else "false"
            text = _inline_markdown_to_html(task_item.group(2))
            output.append(f'<li data-type="taskItem" data-checked="{checked}"><p>{text}</p></li>')
            continue

        bullet = re.fullmatch(r"\s*-\s+(.+)", line)
        if bullet:
            open_list("bullet")
            output.append(f"<li><p>{_inline_markdown_to_html(bullet.group(1))}</p></li>")
            continue

        close_list()
        output.append(f"<p>{_inline_markdown_to_html(line.strip())}</p>")

    close_list()
    return "\n".join(output).strip() + "\n"


def _inline_markdown_to_html(value: str) -> str:
    parts = re.split(r"(`[^`]*`)", value)
    rendered: list[str] = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) >= 2:
            rendered.append(f"<code>{html.escape(part[1:-1])}</code>")
        else:
            rendered.append(_linkify_urls(part))
    return "".join(rendered)


def _linkify_urls(value: str) -> str:
    pieces: list[str] = []
    last = 0
    for match in URL_RE.finditer(value):
        pieces.append(html.escape(value[last : match.start()]))
        url = match.group(0)
        escaped_url = html.escape(url, quote=True)
        pieces.append(
            f'<a target="_blank" rel="noopener noreferrer nofollow" href="{escaped_url}">'
            f"{html.escape(url)}</a>"
        )
        last = match.end()
    pieces.append(html.escape(value[last:]))
    return "".join(pieces)


def _clean_markdown(value: str) -> str:
    lines = [line.rstrip() for line in value.splitlines()]
    compact: list[str] = []
    for line in lines:
        if not line.strip() and compact and not compact[-1].strip():
            continue
        compact.append(line)
    return "\n".join(compact).strip() + "\n"
