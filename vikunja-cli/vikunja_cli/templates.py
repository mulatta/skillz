"""Task template rendering for vikunja-cli."""

from __future__ import annotations

import json
import os
import re
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
SCHEMA_LIST_FIELDS = ("required", "optional", "attachment_expectations")


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

    schema = _read_json_object_for_validation(root / "schema.json", errors)
    defaults = _read_json_object_for_validation(root / "defaults.json", errors)
    _validate_schema_shape(schema, errors)
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
    return {
        "template": loaded.name,
        "required": list(schema.get("required", [])),
        "required_any": [list(group) for group in schema.get("required_any", [])],
        "optional": list(schema.get("optional", [])),
        "attachment_expectations": list(schema.get("attachment_expectations", [])),
        "defaults": loaded.defaults,
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
        schema=cast("TemplateSchema", _read_json_object(root / "schema.json")),
    )


def missing_required(schema: TemplateSchema, context: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for path in schema.get("required", []):
        if not _truthy(_get_path(context, path)):
            missing.append(path)
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


def _validate_schema_shape(schema: dict[str, Any], errors: list[str]) -> None:
    for field in SCHEMA_LIST_FIELDS:
        if field not in schema:
            continue
        if not _is_list_of_strings(schema[field]):
            errors.append(f"schema.json field '{field}' must be a list of strings")

    if "required_any" not in schema:
        return
    groups = schema["required_any"]
    if not isinstance(groups, list) or any(not _is_list_of_strings(group) for group in groups):
        errors.append("schema.json field 'required_any' must be a list of lists of strings")


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


def _is_list_of_strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _has_map(context: dict[str, Any]) -> dict[str, bool]:
    return {key: _truthy(value) for key, value in context.items()}


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


def _clean_markdown(value: str) -> str:
    lines = [line.rstrip() for line in value.splitlines()]
    compact: list[str] = []
    for line in lines:
        if not line.strip() and compact and not compact[-1].strip():
            continue
        compact.append(line)
    return "\n".join(compact).strip() + "\n"
