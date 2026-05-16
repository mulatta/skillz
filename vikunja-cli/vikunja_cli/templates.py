"""Task template rendering for vikunja-cli."""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

import yaml

from vikunja_cli.errors import InputError

URL_RE = re.compile(r"https?://[^\s<>()]+[^\s<>().,;:!?]")
TEMPLATE_FILE_SUFFIX = ".md"
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


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
class TemplateSpec:
    name: str
    description: str
    defaults: dict[str, Any]
    schema: dict[str, Any]
    attachment_expectations: list[str]
    body: str


@dataclass(frozen=True)
class LoadedTemplate:
    name: str
    root: Path
    spec_path: Path
    spec: TemplateSpec

    @property
    def defaults(self) -> dict[str, Any]:
        return dict(self.spec.defaults)

    @property
    def schema(self) -> dict[str, Any]:
        return dict(self.spec.schema)


def default_template_dir() -> Path:
    return default_template_dirs()[0]


def default_template_dirs() -> list[Path]:
    override = os.environ.get("VIKUNJA_TEMPLATE_DIR")
    if override:
        return [Path(override).expanduser()]
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    bases = [data_home, *(Path(item) for item in data_dirs.split(":") if item)]
    return [base / "vikunja-cli" / "templates" for base in bases]


def list_templates(template_dir: Path | None = None) -> list[str]:
    result: set[str] = set()
    for base in _template_bases(template_dir):
        if not base.exists():
            continue
        for item in base.iterdir():
            if item.is_file() and item.suffix == TEMPLATE_FILE_SUFFIX and item.stem != "README":
                try:
                    result.add(_safe_template_name(item.stem))
                except InputError:
                    continue
            elif item.is_dir() and (item / "template.md").is_file():
                try:
                    result.add(_safe_template_name(item.name))
                except InputError:
                    continue
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
        safe_name, spec_path = _resolve_template_path(name, template_dir=template_dir)
        template_name = safe_name
    except InputError as exc:
        return {"template": template_name, "ok": False, "errors": [str(exc)], "warnings": []}

    if not spec_path.exists():
        errors.append(f"missing {safe_name}.md")
        return {"template": template_name, "ok": False, "errors": errors, "warnings": warnings}
    if not spec_path.is_file():
        errors.append(f"{spec_path.name} is not a file")
        return {"template": template_name, "ok": False, "errors": errors, "warnings": warnings}

    try:
        spec = _read_template_spec(spec_path)
    except InputError as exc:
        errors.append(str(exc))
    else:
        if spec.name != safe_name:
            errors.append(f"template name '{spec.name}' does not match file name '{safe_name}'")

    return {"template": template_name, "ok": not errors, "errors": errors, "warnings": warnings}


def validate_templates(template_dir: Path | None = None) -> list[TemplateValidationRecord]:
    return [
        validate_template(name, template_dir=template_dir) for name in list_templates(template_dir)
    ]


def template_required(
    name: str,
    *,
    template_dir: Path | None = None,
) -> TemplateRequiredMetadata:
    loaded = _load_validated_template(name, template_dir=template_dir)
    schema = loaded.schema
    required = _schema_required(schema)
    return {
        "template": loaded.name,
        "required": required,
        "required_any": [],
        "optional": _schema_optional(schema, required),
        "attachment_expectations": list(loaded.spec.attachment_expectations),
        "defaults": loaded.defaults,
    }


def template_schema(
    name: str,
    *,
    template_dir: Path | None = None,
) -> TemplateSchemaMetadata:
    loaded = _load_validated_template(name, template_dir=template_dir)
    return {
        "template": loaded.name,
        "schema": loaded.schema,
        "defaults": loaded.defaults,
        "attachment_expectations": list(loaded.spec.attachment_expectations),
    }


def render_template(
    name: str,
    context: dict[str, Any],
    *,
    template_dir: Path | None = None,
) -> dict[str, Any]:
    loaded = load_template(name, template_dir=template_dir)
    missing = missing_required(loaded.spec, context)
    description = render_description(loaded.spec, context)
    if not missing:
        _validate_complete_context(loaded.spec, context)
    return {
        "template": loaded.name,
        "template_path": str(loaded.spec_path),
        "spec_path": str(loaded.spec_path),
        "defaults": loaded.defaults,
        "schema": loaded.schema,
        "missing_required": missing,
        "description": description,
        "description_html": markdown_to_vikunja_html(description),
    }


def render_description(spec: TemplateSpec, context: dict[str, Any]) -> str:
    summary = str(context.get("summary", "")).strip()
    checklist = _string_list(context.get("checklist"))
    notes = _string_list(context.get("notes"))
    proof = _string_list(context.get("proof"))
    sources = _source_list(context.get("sources"))

    lines: list[str] = ["## Summary", summary, "", "## Checklist"]
    lines.extend(f"- [ ] {item}" for item in checklist)
    if notes:
        lines.extend(["", "## Notes"])
        lines.extend(f"- {item}" for item in notes)
    if proof:
        lines.extend(["", "## Proof"])
        lines.extend(f"- {item}" for item in proof)
    if sources:
        lines.extend(["", "## Sources"])
        for source in sources:
            label = f"{source['kind']}: {source['locator']}"
            title = source.get("title")
            if title:
                label = f"{label} — {title}"
            lines.append(f"- {label}")

    return _clean_markdown("\n".join(lines))


def load_template(name: str, *, template_dir: Path | None = None) -> LoadedTemplate:
    safe_name, spec_path = _resolve_template_path(name, template_dir=template_dir)
    if not spec_path.exists():
        raise InputError(f"template not found: {safe_name}")
    spec = _read_template_spec(spec_path)
    if spec.name != safe_name:
        raise InputError(f"template name '{spec.name}' does not match file name '{safe_name}'")
    return LoadedTemplate(name=safe_name, root=spec_path.parent, spec_path=spec_path, spec=spec)


def missing_required(spec: TemplateSpec, context: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    schema = spec.schema
    required = _schema_required(schema)
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}

    for field in required:
        value = context.get(field)
        prop = properties.get(field, {})
        if _is_missing_value(value):
            missing.append(_missing_label(field, prop))
            continue
        if isinstance(value, list):
            min_items = prop.get("minItems") if isinstance(prop, dict) else None
            if isinstance(min_items, int) and len(value) < min_items:
                missing.append(f"{field} (minItems {min_items})")

    return _dedupe(missing)


def _load_validated_template(name: str, *, template_dir: Path | None = None) -> LoadedTemplate:
    validation = validate_template(name, template_dir=template_dir)
    if validation["errors"]:
        raise InputError("template validation failed: " + "; ".join(validation["errors"]))
    return load_template(name, template_dir=template_dir)


def _resolve_template_path(
    name: str,
    *,
    template_dir: Path | None = None,
) -> tuple[str, Path]:
    safe_name = _safe_template_name(name)
    fallback_path: Path | None = None
    for base in _template_bases(template_dir):
        resolved_base = base.expanduser().resolve()
        candidates = [
            resolved_base / f"{safe_name}.md",
            resolved_base / safe_name / "template.md",
        ]
        if fallback_path is None:
            fallback_path = candidates[0]
        for path in candidates:
            root = path.parent.resolve()
            try:
                root.relative_to(resolved_base)
            except ValueError as exc:
                raise InputError("template path escapes template dir") from exc
            if path.exists():
                return safe_name, path.resolve()
    return safe_name, fallback_path or (
        default_template_dir().expanduser().resolve() / f"{safe_name}.md"
    )


def _template_bases(template_dir: Path | None = None) -> list[Path]:
    if template_dir is not None:
        return [template_dir.expanduser()]
    return default_template_dirs()


def _safe_template_name(name: str) -> str:
    trimmed = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", trimmed):
        raise InputError("template must contain only letters, numbers, '_' or '-'")
    return trimmed


def _read_template_spec(path: Path) -> TemplateSpec:
    text = path.read_text()
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise InputError(f"{path.name} must start with YAML frontmatter")
    frontmatter, body = match.groups()
    try:
        raw = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        raise InputError(f"invalid YAML in {path.name}: {exc}") from None
    if not isinstance(raw, dict):
        raise InputError(f"{path.name} frontmatter must be a YAML mapping")
    return _parse_template_spec(path.name, raw, body)


def _parse_template_spec(filename: str, raw: dict[Any, Any], body: str) -> TemplateSpec:
    errors: list[str] = []
    allowed = {"name", "description", "defaults", "schema", "attachment_expectations"}
    for key in raw:
        if key not in allowed:
            errors.append(f"unsupported key: {key}")

    name = raw.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        errors.append("name must contain only letters, numbers, '_' or '-'")
        name = ""

    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("description must be a non-empty string")
        description = ""

    defaults = raw.get("defaults")
    if not isinstance(defaults, dict):
        errors.append("defaults must be a mapping")
        defaults = {}
    else:
        default_errors = _validate_defaults(defaults)
        errors.extend(default_errors)

    schema = raw.get("schema")
    if not isinstance(schema, dict):
        errors.append("schema must be a mapping")
        schema = {}
    else:
        errors.extend(_validate_schema_shape(schema))

    attachment_expectations = raw.get("attachment_expectations", [])
    if not _is_list_of_strings(attachment_expectations):
        errors.append("attachment_expectations must be a list of strings")
        attachment_expectations = []

    if errors:
        raise InputError(f"invalid template spec in {filename}: " + "; ".join(errors))

    return TemplateSpec(
        name=name,
        description=description,
        defaults=dict(defaults),
        schema=dict(schema),
        attachment_expectations=list(attachment_expectations),
        body=body,
    )


def _validate_defaults(defaults: dict[Any, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {"priority", "labels"}
    for key in defaults:
        if key not in allowed:
            errors.append(f"defaults.{key} is unsupported")
    priority = defaults.get("priority")
    if not isinstance(priority, int) or priority < 0 or priority > 5:
        errors.append("defaults.priority must be an integer from 0 to 5")
    labels = defaults.get("labels", [])
    if not _is_list_of_strings(labels):
        errors.append("defaults.labels must be a list of strings")
    elif any(not item.strip() for item in labels):
        errors.append("defaults.labels must not contain empty strings")
    return errors


def _validate_schema_shape(schema: dict[Any, Any]) -> list[str]:
    errors: list[str] = []
    if schema.get("type") != "object":
        errors.append("schema.type must be object")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        errors.append("schema.properties must be a mapping")
    required = schema.get("required", [])
    if not _is_list_of_strings(required):
        errors.append("schema.required must be a list of strings")
    defs = schema.get("$defs", {})
    if defs is not None and not isinstance(defs, dict):
        errors.append("schema.$defs must be a mapping")
    errors.extend(_validate_schema_node(schema, schema, ["schema"]))
    return errors


def _validate_schema_node(node: Any, root: dict[Any, Any], path: list[str]) -> list[str]:
    if not isinstance(node, dict):
        return []
    errors: list[str] = []
    ref = node.get("$ref")
    if ref is not None:
        if not isinstance(ref, str) or not _resolve_ref(root, ref):
            errors.append(f"{'.'.join(path)}.$ref points to an unknown definition")
        return errors

    node_type = node.get("type")
    if node_type == "array":
        min_items = node.get("minItems")
        max_items = node.get("maxItems")
        if min_items is not None and (not isinstance(min_items, int) or min_items < 0):
            errors.append(f"{'.'.join(path)}.minItems must be a non-negative integer")
        if max_items is not None and (not isinstance(max_items, int) or max_items < 0):
            errors.append(f"{'.'.join(path)}.maxItems must be a non-negative integer")
        if isinstance(min_items, int) and isinstance(max_items, int) and min_items > max_items:
            errors.append(f"{'.'.join(path)}.minItems must be less than or equal to maxItems")
        errors.extend(_validate_schema_node(node.get("items"), root, [*path, "items"]))
    if node_type == "object":
        required = node.get("required", [])
        if not _is_list_of_strings(required):
            errors.append(f"{'.'.join(path)}.required must be a list of strings")
        properties = node.get("properties", {})
        if properties is not None and not isinstance(properties, dict):
            errors.append(f"{'.'.join(path)}.properties must be a mapping")
        elif isinstance(properties, dict):
            for key, value in properties.items():
                errors.extend(_validate_schema_node(value, root, [*path, "properties", str(key)]))
    defs = node.get("$defs")
    if isinstance(defs, dict):
        for key, value in defs.items():
            errors.extend(_validate_schema_node(value, root, [*path, "$defs", str(key)]))
    enum = node.get("enum")
    if enum is not None and not isinstance(enum, list):
        errors.append(f"{'.'.join(path)}.enum must be a list")
    return errors


def _validate_complete_context(spec: TemplateSpec, context: dict[str, Any]) -> None:
    errors = _validate_value(context, spec.schema, spec.schema, [])
    if errors:
        raise InputError(f"template context failed validation: {'; '.join(errors)}") from None


def _validate_value(
    value: Any,
    schema: dict[Any, Any],
    root: dict[Any, Any],
    path: list[str | int],
) -> list[str]:
    ref = schema.get("$ref")
    if isinstance(ref, str):
        resolved = _resolve_ref(root, ref)
        if resolved is None:
            return [_schema_path(path) + "unknown schema reference"]
        return _validate_value(value, resolved, root, path)

    errors: list[str] = []
    node_type = schema.get("type")
    if node_type == "object":
        if not isinstance(value, dict):
            return [f"{_schema_path(path)}must be an object"]
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        required = schema.get("required", [])
        if _is_list_of_strings(required):
            for field in required:
                if _is_missing_value(value.get(field)):
                    errors.append(f"{_schema_path([*path, field])}is required")
        if schema.get("additionalProperties") is False:
            for field in value:
                if field not in properties:
                    errors.append(f"{_schema_path([*path, str(field)])}is not allowed")
        for field, item in value.items():
            if field in properties and isinstance(properties[field], dict):
                errors.extend(_validate_value(item, properties[field], root, [*path, str(field)]))
        return errors

    if node_type == "array":
        if not isinstance(value, list):
            return [f"{_schema_path(path)}must be an array"]
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{_schema_path(path)}needs at least {min_items} items")
        if isinstance(max_items, int) and len(value) > max_items:
            errors.append(f"{_schema_path(path)}needs at most {max_items} items")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_value(item, items, root, [*path, index]))
        return errors

    if node_type == "string":
        if not isinstance(value, str):
            return [f"{_schema_path(path)}must be a string"]
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{_schema_path(path)}must be at least {min_length} characters")
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            errors.append(
                f"{_schema_path(path)}must be one of: {', '.join(str(item) for item in enum)}"
            )
        return errors

    return errors


def _resolve_ref(root: dict[Any, Any], ref: str) -> dict[Any, Any] | None:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        return None
    defs = root.get("$defs")
    if not isinstance(defs, dict):
        return None
    value = defs.get(ref.removeprefix(prefix))
    return value if isinstance(value, dict) else None


def _schema_path(path: list[str | int]) -> str:
    return ".".join(str(item) for item in path) + ": " if path else ""


def _schema_required(schema: dict[str, Any]) -> list[str]:
    required = schema.get("required", [])
    return list(required) if _is_list_of_strings(required) else []


def _schema_optional(schema: dict[str, Any], required: list[str]) -> list[str]:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return []
    required_set = set(required)
    return [key for key in properties if key not in required_set]


def _missing_label(field: str, property_schema: Any) -> str:
    if isinstance(property_schema, dict):
        min_items = property_schema.get("minItems")
        if isinstance(min_items, int) and min_items > 0 and property_schema.get("type") == "array":
            return f"{field} (minItems {min_items})"
    return field


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def _is_list_of_strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _source_list(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        locator = item.get("locator")
        title = item.get("title")
        if not isinstance(kind, str) or not isinstance(locator, str):
            continue
        source = {"kind": kind, "locator": locator}
        if isinstance(title, str) and title.strip():
            source["title"] = title
        result.append(source)
    return result


def markdown_to_vikunja_html(value: str) -> str:
    """Convert template Markdown subset to TipTap HTML stored by Vikunja descriptions."""
    lines = [line.rstrip() for line in value.splitlines()]
    output: list[str] = []
    list_kind: Literal["task", "bullet"] | None = None

    def close_list() -> None:
        nonlocal list_kind
        if list_kind is None:
            return
        output.append("</ul>")
        list_kind = None

    def open_list(kind: Literal["task", "bullet"]) -> None:
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
