"""zhost-cli entry point.

Noun > verb commands for a self-hosted Zotero library (zhost):

  item        add / list / find / get / edit / move / remove   (papers and others)
  collection  list / create / rename / move / items / remove   (folders)
  library     export / import   (whole-library archive)
  highlight   add / list
  note        add / list
  tag         add / remove / list
  pdf         attach / fetch / replace
  api         raw escape hatch

`item add` is composite — it creates an item and, in one call, attaches a PDF,
files it in a collection (created if absent), and tags it. Deletion is unified:
`item remove` deletes any item (paper, attachment, highlight, note);
`collection remove` removes a folder (its items stay); `tag remove` only detaches
a tag. `item add` creates, `item edit` modifies — using add to update duplicates.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zhost_cli.client import Client
from zhost_cli.config import load_config, run_key_command, write_config
from zhost_cli.errors import APIError, CLIError, InputError
from zhost_cli.keys import valid_object_key
from zhost_cli.output import emit, emit_json, emit_table, read_json_input, short, truncate

Handler = Callable[[Client, argparse.Namespace], None]

# Agent-applied tags use Zotero's "automatic" type (1) so the UI distinguishes
# them from manual tags and they can be cleaned up in bulk later.
AGENT_TAG_TYPE = 1
DEFAULT_COLOR = "#ffd400"  # Zotero yellow


def make_client(config_path: str | None = None) -> Client:
    cfg = load_config(Path(config_path) if config_path else None)
    return Client(cfg.base_url, cfg.api_key, cfg.user_id, cfg.timeout)


# == item =================================================================


def cmd_item_add(client: Client, ns: argparse.Namespace) -> None:
    collection = ensure_collection(client, ns.collection) if ns.collection else None
    if ns.file:
        objects = read_json_input(ns.file)
        if not isinstance(objects, list):
            raise InputError("--file must contain a JSON array of item objects")
    else:
        item = build_item(ns)
        if collection:
            item["collections"] = [collection]
        objects = [item]
    paper = created_key(client.write("item", objects))
    result: dict[str, Any] = {"item": paper}
    if collection:
        result["collection"] = collection
    if ns.pdf:
        result["attachment"] = attach_pdf(client, paper, ns.pdf, ns.tag)
    if ns.use_json:
        emit_json(result)
    else:
        print(paper)


def cmd_item_find(client: Client, ns: argparse.Namespace) -> None:
    query: dict[str, Any] = {"q": ns.query, "qmode": "everything", "limit": ns.limit}
    put_if(query, "itemType", ns.type)
    if ns.tag:
        query["tag"] = ns.tag
    hits, _ = client.query("/items", query)
    emit(resolve_papers(client, hits), use_json=ns.use_json, text_fn=print_items)


def cmd_item_get(client: Client, ns: argparse.Namespace) -> None:
    require_key(ns.key)
    items = client.objects("item", [ns.key])
    if not items:
        raise InputError(f"item not found: {ns.key}")
    children = gather_children(client, ns.key)
    if ns.use_json:
        emit_json({"item": items[0], "children": children})
    else:
        print_detail(items[0], children)


def cmd_item_list(client: Client, ns: argparse.Namespace) -> None:
    """A full, paged dump of item records — the first-class bulk read (replaces
    the `api` escape hatch). Top-level only by default; `--all` adds children."""
    suffix = "/items/trash" if ns.trash else "/items" if ns.all else "/items/top"
    if ns.collection:
        key = find_collection(client, ns.collection)
        if key is None:
            raise InputError(f"collection not found: {ns.collection}")
        suffix = f"/collections/{key}/items" + ("" if ns.all else "/top")
    params: dict[str, Any] = {}
    put_if(params, "itemType", ns.type)
    if ns.tag:
        params["tag"] = ns.tag
    emit(client.query_all(suffix, params), use_json=ns.use_json, text_fn=print_items)


def cmd_item_edit(client: Client, ns: argparse.Namespace) -> None:
    require_key(ns.key)
    if ns.file:
        data = read_json_input(ns.file)
        if not isinstance(data, dict):
            raise InputError("--file must contain a single JSON object of fields")
    else:
        data = dict(parse_set(item) for item in ns.set)
    if not data:
        raise InputError("nothing to edit; pass --set field=value or --file")
    data["key"] = ns.key
    client.write("item", [data], method="PATCH")
    print(f"edited {ns.key}")


def cmd_item_move(client: Client, ns: argparse.Namespace) -> None:
    require_key(ns.key)
    names = [n.strip() for value in ns.collection for n in value.split(",") if n.strip()]
    keys = [ensure_collection(client, name) for name in names]
    client.write("item", [{"key": ns.key, "collections": keys}], method="PATCH")
    print(f"moved {ns.key} -> {','.join(keys)}")


def cmd_item_remove(client: Client, ns: argparse.Namespace) -> None:
    require_yes(ns)
    require_key(ns.key)
    client.delete("item", [ns.key])
    print(f"deleted {ns.key}")


# == collection ===========================================================


def cmd_coll_list(client: Client, ns: argparse.Namespace) -> None:
    collections = all_collections(client)
    if ns.use_json:
        emit_json(collections)
        return
    children: dict[str | None, list[dict[str, Any]]] = {}
    for c in collections:
        parent = c.get("data", {}).get("parentCollection") or None
        children.setdefault(parent, []).append(c)

    def walk(parent: str | None, depth: int) -> None:
        for c in sorted(children.get(parent, []), key=lambda x: x["data"].get("name", "").lower()):
            print("  " * depth + f"{short(c.get('key'))}  {short(c['data'].get('name'))}")
            walk(c["key"], depth + 1)

    walk(None, 0)


def cmd_coll_create(client: Client, ns: argparse.Namespace) -> None:
    obj: dict[str, Any] = {"name": ns.name}
    if ns.parent:
        require_key(ns.parent)
        obj["parentCollection"] = ns.parent
    print(created_key(client.write("collection", [obj])))


def cmd_coll_rename(client: Client, ns: argparse.Namespace) -> None:
    require_key(ns.key)
    client.write("collection", [{"key": ns.key, "name": ns.name}], method="PATCH")
    print(f"renamed {ns.key}")


def cmd_coll_move(client: Client, ns: argparse.Namespace) -> None:
    require_key(ns.key)
    if ns.top:
        parent: Any = False
    elif ns.parent:
        require_key(ns.parent)
        parent = ns.parent
    else:
        raise InputError("pass --parent KEY or --top")
    client.write("collection", [{"key": ns.key, "parentCollection": parent}], method="PATCH")
    print(f"moved {ns.key}")


def cmd_coll_items(client: Client, ns: argparse.Namespace) -> None:
    require_key(ns.key)
    query: dict[str, Any] = {"limit": ns.limit}
    put_if(query, "itemType", ns.type)
    if ns.tag:
        query["tag"] = ns.tag
    items, _ = client.query(f"/collections/{ns.key}/items", query)
    emit(items, use_json=ns.use_json, text_fn=print_items)


def cmd_coll_remove(client: Client, ns: argparse.Namespace) -> None:
    require_yes(ns)
    require_key(ns.key)
    client.delete("collection", [ns.key])
    print(f"deleted collection {ns.key} (items kept)")


# == highlight ============================================================


def cmd_hl_add(client: Client, ns: argparse.Namespace) -> None:
    from zhost_cli import pdf

    attachment = pdf_attachment(client, ns.item)
    located = pdf.locate(ns.pdf, ns.text)
    top_y = int(max((r[3] for r in located.rects), default=0))
    annotation: dict[str, Any] = {
        "itemType": "annotation",
        "parentItem": attachment,
        "annotationType": "highlight",
        "annotationText": ns.text,
        "annotationColor": ns.color,
        "annotationPageLabel": ns.page or str(located.page_index + 1),
        "annotationSortIndex": f"{located.page_index:05d}|000000|{top_y:05d}",
        "annotationPosition": located.position_json(),
        "tags": agent_tags(ns.tag),
    }
    if ns.comment:
        annotation["annotationComment"] = ns.comment
    print(created_key(client.write("item", [annotation])))


def cmd_hl_list(client: Client, ns: argparse.Namespace) -> None:
    attachment = pdf_attachment(client, ns.item)
    anns = [c for c in gather_children(client, attachment) if _is(c, "annotation")]
    emit(anns, use_json=ns.use_json, text_fn=print_annotations)


# == note =================================================================


def cmd_note_add(client: Client, ns: argparse.Namespace) -> None:
    require_key(ns.item)
    html = read_text(ns.file) if ns.file else ns.text
    if not html:
        raise InputError("provide --text or --file for the note body")
    note = {"itemType": "note", "parentItem": ns.item, "note": html, "tags": agent_tags(ns.tag)}
    print(created_key(client.write("item", [note])))


def cmd_note_list(client: Client, ns: argparse.Namespace) -> None:
    require_key(ns.item)
    notes = [c for c in gather_children(client, ns.item) if _is(c, "note")]
    emit(notes, use_json=ns.use_json, text_fn=print_items)


# == tag ==================================================================


def cmd_tag_add(client: Client, ns: argparse.Namespace) -> None:
    apply_tags(client, ns.key, add=ns.name, remove=[])
    print(f"tagged {ns.key}")


def cmd_tag_remove(client: Client, ns: argparse.Namespace) -> None:
    apply_tags(client, ns.key, add=[], remove=ns.name)
    print(f"untagged {ns.key}")


def cmd_tag_list(client: Client, ns: argparse.Namespace) -> None:
    if ns.key:
        require_key(ns.key)
        items = client.objects("item", [ns.key])
        tags = items[0].get("data", {}).get("tags", []) if items else []
        if ns.use_json:
            emit_json(tags)
        else:
            emit_table(["TAG", "TYPE"], [[short(t.get("tag")), short(t.get("type"))] for t in tags])
    else:
        resp = client.request("GET", client.user_path("/tags"))
        emit(resp.json(), use_json=ns.use_json, text_fn=print_tags)


# == pdf ==================================================================


def cmd_pdf_attach(client: Client, ns: argparse.Namespace) -> None:
    require_key(ns.item)
    print(attach_pdf(client, ns.item, ns.pdf, ns.tag))


def cmd_pdf_fetch(client: Client, ns: argparse.Namespace) -> None:
    attachment = pdf_attachment(client, ns.item)
    size = client.download_file(attachment, ns.output)
    print(f"wrote {ns.output} ({size} bytes)")


def cmd_pdf_replace(client: Client, ns: argparse.Namespace) -> None:
    attachment = pdf_attachment(client, ns.item)
    current = client.objects("item", [attachment])
    old_md5 = current[0]["data"].get("md5") if current else None
    if not old_md5:
        raise InputError(f"{attachment} has no current file to replace")
    client.upload_file(attachment, ns.pdf, replace_md5=old_md5)
    print(f"replaced file on {attachment}")


# == setup / api ==========================================================


def cmd_setup(ns: argparse.Namespace) -> None:
    path = write_config(
        ns.base_url, ns.api_key_command, ns.user_id, Path(ns.config) if ns.config else None
    )
    key = run_key_command(ns.api_key_command)
    print(f"Wrote {path}")
    if key:
        print("API key command works")
    else:
        raise InputError("api_key_command did not return a key")


def cmd_api(client: Client, ns: argparse.Namespace) -> None:
    body = None
    if ns.body and ns.file:
        raise InputError("use --body or --file, not both")
    if ns.body:
        try:
            body = json.dumps(json.loads(ns.body)).encode()
        except json.JSONDecodeError as exc:
            raise InputError(f"invalid JSON body: {exc}") from None
    elif ns.file:
        body = json.dumps(read_json_input(ns.file)).encode()
    query = dict(parse_set(item) for item in ns.query)
    headers = dict(parse_set(item) for item in ns.header)
    resp = client.request(
        ns.method,
        ns.path,
        body=body,
        content_type="application/json" if body else None,
        query=query,
        extra_headers=headers or None,
    )
    emit_json(resp.json())


# == library (whole-library archive) ======================================


def cmd_library_export(client: Client, ns: argparse.Namespace) -> None:
    """Serialize the library to a directory: a record per top-level item with its
    children, attachment files, and full-text index nested in; plus the
    collection tree and tag list. The inverse of `library import`."""
    outdir = Path(ns.outdir)
    (outdir / "items").mkdir(parents=True, exist_ok=True)
    version = client.library_version()

    children = children_by_parent(client.query_all("/items"))
    if ns.collection:
        key = find_collection(client, ns.collection)
        if key is None:
            raise InputError(f"collection not found: {ns.collection}")
        tops = client.query_all(f"/collections/{key}/items/top")
    else:
        tops = client.query_all("/items/top")

    for top in tops:
        kids = children.get(str(top["key"]), [])
        fulltext: dict[str, Any] = {}
        for child in kids:
            if child.get("data", {}).get("itemType") != "attachment":
                continue
            ckey = str(child["key"])
            if not ns.no_files:
                export_file(client, child, outdir / "files" / ckey)
            ft = client.fulltext(ckey)
            if ft is not None:
                fulltext[ckey] = ft
        record = {"item": top, "children": kids, "fulltext": fulltext}
        (outdir / "items" / f"{top['key']}.json").write_text(json.dumps(record, indent=2))

    collections = all_collections(client)
    (outdir / "collections.json").write_text(json.dumps(collections, indent=2))
    tags = client.request("GET", client.user_path("/tags")).json()
    (outdir / "tags.json").write_text(json.dumps(tags, indent=2))
    manifest = {
        "libraryVersion": version,
        "counts": {"items": len(tops), "collections": len(collections)},
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"exported {len(tops)} items to {outdir}")


def cmd_library_import(client: Client, ns: argparse.Namespace) -> None:
    """Recreate a library from a `library export` directory. Object keys are
    preserved, so parent-child and collection links survive the round-trip; run
    it against an empty (or matching) library."""
    indir = Path(ns.indir)
    if not (indir / "manifest.json").exists():
        raise InputError(f"not an export directory (no manifest.json): {indir}")

    collections = json.loads((indir / "collections.json").read_text())
    import_collections(client, collections)

    count = 0
    for path in sorted((indir / "items").glob("*.json")):
        rec = json.loads(path.read_text())
        client.write("item", [restorable(rec["item"]["data"])])
        for child in rec.get("children", []):
            ckey = str(child["key"])
            client.write("item", [restorable(child["data"])])
            files = indir / "files" / ckey
            if not ns.no_files and files.is_dir():
                for fp in sorted(files.iterdir()):
                    client.upload_file(ckey, str(fp))
            ft = rec.get("fulltext", {}).get(ckey)
            if ft is not None:
                client.put_fulltext(ckey, ft)
        count += 1
    print(f"imported {count} items into the library")


def children_by_parent(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group items by their parentItem key (one pass over the whole library)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        parent = item.get("data", {}).get("parentItem")
        if parent:
            out.setdefault(str(parent), []).append(item)
    return out


def export_file(client: Client, attachment: dict[str, Any], dest: Path) -> None:
    """Download an attachment's file into `dest/<filename>`, skipping attachments
    that never had a file uploaded (no stored md5)."""
    data = attachment.get("data", {})
    filename = data.get("filename")
    if not filename or not data.get("md5"):
        return
    dest.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(str(attachment["key"]), str(dest / filename))
    except APIError:
        pass  # file registered but bytes missing in object storage; skip


def import_collections(client: Client, collections: list[dict[str, Any]]) -> None:
    """Recreate collections parents-first so parentCollection links resolve."""
    by_key = {str(c["key"]): c for c in collections}
    done: set[str] = set()

    def emit_one(coll: dict[str, Any]) -> None:
        key = str(coll["key"])
        if key in done:
            return
        parent = coll.get("data", {}).get("parentCollection")
        if parent and str(parent) in by_key:
            emit_one(by_key[str(parent)])
        client.write("collection", [restorable(coll["data"])])
        done.add(key)

    for coll in collections:
        emit_one(coll)


def restorable(data: dict[str, Any]) -> dict[str, Any]:
    """An object's data ready to re-create: keep its key, drop the stale version
    (a create must not carry the source library's version)."""
    out = dict(data)
    out.pop("version", None)
    return out


# == shared helpers =======================================================


def find_collection(client: Client, name: str) -> str | None:
    """The key of the collection named `name`, or None if there is none."""
    for item in all_collections(client):
        if str(item.get("data", {}).get("name", "")) == name:
            return str(item["key"])
    return None


def ensure_collection(client: Client, name: str) -> str:
    """Find a collection by name or create it (idempotent)."""
    key = find_collection(client, name)
    return key if key is not None else created_key(client.write("collection", [{"name": name}]))


def all_collections(client: Client) -> list[dict[str, Any]]:
    keys = list(client.versions("collection").keys())
    return client.objects("collection", keys)


def attach_pdf(client: Client, parent: str, pdf: str, tags: list[str] | None) -> str:
    """Create an imported_file attachment under `parent` and upload the PDF."""
    attachment = {
        "itemType": "attachment",
        "parentItem": parent,
        "linkMode": "imported_file",
        "title": "Full Text PDF",
        "filename": Path(pdf).name,
        "contentType": "application/pdf",
        "tags": agent_tags(tags),
    }
    key = created_key(client.write("item", [attachment]))
    client.upload_file(key, pdf)
    return key


def resolve_papers(client: Client, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map full-text hits (which land on attachments) up to parent papers, deduped."""
    keys: list[str] = []
    for hit in hits:
        key = hit.get("data", {}).get("parentItem") or hit.get("key")
        if key and key not in keys:
            keys.append(str(key))
    return client.objects("item", keys)


def gather_children(client: Client, parent: str) -> list[dict[str, Any]]:
    """Items whose parentItem is `parent`. zhost has no parentItem filter, so this
    lists items and filters client-side — fine for a personal library."""
    items, _ = client.query("/items", {"limit": 1000})
    return [it for it in items if it.get("data", {}).get("parentItem") == parent]


def pdf_attachment(client: Client, key: str) -> str:
    """Resolve a key to its PDF attachment: an attachment key returns as-is, an item
    key resolves to its first PDF child."""
    require_key(key)
    items = client.objects("item", [key])
    if items and _is(items[0], "attachment"):
        return key
    for child in gather_children(client, key):
        data = child.get("data", {})
        is_pdf = data.get("contentType") == "application/pdf" or str(
            data.get("filename", "")
        ).lower().endswith(".pdf")
        if _is(child, "attachment") and is_pdf:
            return str(child["key"])
    raise InputError(f"no PDF attachment found under {key}")


def apply_tags(client: Client, key: str, *, add: list[str], remove: list[str]) -> None:
    require_key(key)
    items = client.objects("item", [key])
    if not items:
        raise InputError(f"item not found: {key}")
    tags = list(items[0].get("data", {}).get("tags", []) or [])
    drop = set(remove)
    tags = [t for t in tags if t.get("tag") not in drop]
    have = {t.get("tag") for t in tags}
    for name in add:
        if name not in have:
            tags.append({"tag": name, "type": AGENT_TAG_TYPE})
    client.write("item", [{"key": key, "tags": tags}], method="PATCH")


def build_item(ns: argparse.Namespace) -> dict[str, Any]:
    item: dict[str, Any] = {"itemType": ns.type, "title": ns.title}
    if ns.author:
        item["creators"] = [creator(name) for name in ns.author]
    put_if(item, "date", ns.date)
    put_if(item, "DOI", ns.doi)
    put_if(item, "publicationTitle", ns.journal)
    put_if(item, "url", ns.url)
    item["tags"] = agent_tags(ns.tag)
    return item


def creator(name: str) -> dict[str, str]:
    first, _, last = name.rpartition(" ")
    return {"creatorType": "author", "firstName": first, "lastName": last}


def agent_tags(tags: list[str] | None) -> list[dict[str, Any]]:
    return [{"tag": tag, "type": AGENT_TAG_TYPE} for tag in (tags or [])]


def created_key(resp: Any) -> str:
    data = resp.json()
    try:
        return str(data["successful"]["0"]["key"])
    except (KeyError, TypeError) as exc:
        raise InputError(f"write did not return a key: {data!r}") from exc


def _is(item: dict[str, Any], item_type: str) -> bool:
    return bool(item.get("data", {}).get("itemType") == item_type)


def require_yes(ns: argparse.Namespace) -> None:
    if not ns.yes:
        raise InputError("destructive command requires --yes")


def require_key(key: str) -> None:
    if not valid_object_key(key):
        raise InputError(f"invalid object key (8 chars, no 0/1/O/L): {key}")


def parse_set(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise InputError(f"expected KEY=VALUE: {value}")
    key, val = value.split("=", 1)
    if not key:
        raise InputError(f"key must not be empty: {value}")
    return key, val


def put_if(data: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        data[key] = value


def read_text(path: str) -> str:
    try:
        if path == "-":
            return sys.stdin.read()
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None


# == renderers ============================================================


def print_items(data: Any) -> None:
    rows = []
    for x in as_list(data):
        d = x.get("data", {})
        rows.append(
            [
                short(x.get("key")),
                short(d.get("itemType")),
                truncate(d.get("title") or d.get("note")),
            ]
        )
    emit_table(["KEY", "TYPE", "TITLE"], rows)


def print_annotations(data: Any) -> None:
    rows = []
    for x in as_list(data):
        d = x.get("data", {})
        rows.append(
            [
                short(x.get("key")),
                short(d.get("annotationColor")),
                truncate(d.get("annotationText"), 50),
                truncate(d.get("annotationComment"), 30),
            ]
        )
    emit_table(["KEY", "COLOR", "TEXT", "COMMENT"], rows)


def print_tags(data: Any) -> None:
    rows = [[short(x.get("tag")), short(x.get("numItems"))] for x in as_list(data)]
    emit_table(["TAG", "ITEMS"], rows)


def print_detail(item: dict[str, Any], children: list[dict[str, Any]]) -> None:
    data = item.get("data", {})
    print(f"key:    {short(item.get('key'))}")
    print(f"type:   {short(data.get('itemType'))}")
    print(f"title:  {short(data.get('title') or data.get('note'))}")
    if data.get("collections"):
        print(f"collections: {', '.join(data['collections'])}")
    if data.get("tags"):
        print(f"tags:   {', '.join(t.get('tag', '') for t in data['tags'])}")
    if children:
        print("children:")
        for child in children:
            cd = child.get("data", {})
            label = cd.get("annotationText") or cd.get("filename") or cd.get("note") or ""
            print(
                f"  {short(child.get('key'))}  {short(cd.get('itemType')):11}  {truncate(label, 60)}"
            )


def as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


# == parser ===============================================================


def add_tag_opt(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tag", action="append", help="Tag (repeatable)")


def _item(sub: Any) -> None:
    item = sub.add_parser("item", help="Items (papers and others)")
    vs = item.add_subparsers(dest="verb")

    s = vs.add_parser("add", help="Create an item (optionally with PDF, collection, tags)")
    s.add_argument("--type", default="journalArticle")
    s.add_argument("--title")
    s.add_argument("--author", action="append", help="'First Last' (repeatable)")
    s.add_argument("--date")
    s.add_argument("--doi")
    s.add_argument("--journal")
    s.add_argument("--url")
    s.add_argument("--pdf", help="PDF to attach and upload")
    s.add_argument("--collection", help="Collection name (created if absent)")
    add_tag_opt(s)
    s.add_argument("--file", help="JSON array of item objects (overrides fields)")
    s.set_defaults(handler=cmd_item_add)

    s = vs.add_parser("list", help="List items (default: top-level); a full paged dump")
    s.add_argument("--all", action="store_true", help="Include children (attachments, notes)")
    s.add_argument("--trash", action="store_true", help="List trashed items instead")
    s.add_argument("--collection", help="Restrict to a collection (by name)")
    s.add_argument("--type")
    add_tag_opt(s)
    s.set_defaults(handler=cmd_item_list)

    s = vs.add_parser("find", help="Full-text search (title + attachment text) -> items")
    s.add_argument("query")
    s.add_argument("--type")
    add_tag_opt(s)
    s.add_argument("--limit", type=int, default=25)
    s.set_defaults(handler=cmd_item_find)

    s = vs.add_parser("get", help="Show an item with its children")
    s.add_argument("key")
    s.set_defaults(handler=cmd_item_get)

    s = vs.add_parser("edit", help="Change fields (empty value clears)")
    s.add_argument("key")
    s.add_argument("--set", action="append", default=[], help="field=VALUE (repeatable)")
    s.add_argument("--file", help="JSON object of fields")
    s.set_defaults(handler=cmd_item_edit)

    s = vs.add_parser("move", help="Re-file into collections (replaces membership)")
    s.add_argument("key")
    s.add_argument("--collection", action="append", required=True, help="Name (repeatable / comma)")
    s.set_defaults(handler=cmd_item_move)

    s = vs.add_parser("remove", help="Delete any item")
    s.add_argument("key")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(handler=cmd_item_remove)


def _collection(sub: Any) -> None:
    coll = sub.add_parser("collection", help="Collections (folders)")
    vs = coll.add_subparsers(dest="verb")

    vs.add_parser("list", help="List collections as a tree").set_defaults(handler=cmd_coll_list)

    s = vs.add_parser("create")
    s.add_argument("name")
    s.add_argument("--parent", help="Parent collection key")
    s.set_defaults(handler=cmd_coll_create)

    s = vs.add_parser("rename")
    s.add_argument("key")
    s.add_argument("name")
    s.set_defaults(handler=cmd_coll_rename)

    s = vs.add_parser("move", help="Reparent a collection")
    s.add_argument("key")
    s.add_argument("--parent", help="New parent collection key")
    s.add_argument("--top", action="store_true", help="Move to top level")
    s.set_defaults(handler=cmd_coll_move)

    s = vs.add_parser("items", help="Items in a collection")
    s.add_argument("key")
    s.add_argument("--type")
    add_tag_opt(s)
    s.add_argument("--limit", type=int, default=100)
    s.set_defaults(handler=cmd_coll_items)

    s = vs.add_parser("remove", help="Delete a folder (its items stay)")
    s.add_argument("key")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(handler=cmd_coll_remove)


def _library(sub: Any) -> None:
    lib = sub.add_parser("library", help="Whole-library archive (export / import)")
    vs = lib.add_subparsers(dest="verb")

    s = vs.add_parser("export", help="Dump the whole library to a directory")
    s.add_argument("outdir")
    s.add_argument("--collection", help="Restrict to a collection (by name)")
    s.add_argument(
        "--no-files", action="store_true", dest="no_files", help="Skip attachment file bytes"
    )
    s.set_defaults(handler=cmd_library_export)

    s = vs.add_parser("import", help="Restore a library from an export directory")
    s.add_argument("indir")
    s.add_argument(
        "--no-files", action="store_true", dest="no_files", help="Skip attachment file uploads"
    )
    s.set_defaults(handler=cmd_library_import)


def _highlight(sub: Any) -> None:
    hl = sub.add_parser("highlight", help="Highlights")
    vs = hl.add_subparsers(dest="verb")
    s = vs.add_parser("add", help="Highlight exact PDF text")
    s.add_argument("item", help="Item or attachment key")
    s.add_argument("--pdf", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--color", default=DEFAULT_COLOR, help=f"Hex (default {DEFAULT_COLOR})")
    s.add_argument("--comment")
    s.add_argument("--page")
    add_tag_opt(s)
    s.set_defaults(handler=cmd_hl_add)
    s = vs.add_parser("list")
    s.add_argument("item")
    s.set_defaults(handler=cmd_hl_list)


def _note(sub: Any) -> None:
    note = sub.add_parser("note", help="Notes")
    vs = note.add_subparsers(dest="verb")
    s = vs.add_parser("add")
    s.add_argument("item")
    s.add_argument("--text", help="Note body (HTML)")
    s.add_argument("--file", help="Note body file or - for stdin")
    add_tag_opt(s)
    s.set_defaults(handler=cmd_note_add)
    s = vs.add_parser("list")
    s.add_argument("item")
    s.set_defaults(handler=cmd_note_list)


def _tag(sub: Any) -> None:
    tag = sub.add_parser("tag", help="Tags on items")
    vs = tag.add_subparsers(dest="verb")
    s = vs.add_parser("add")
    s.add_argument("key")
    s.add_argument("name", nargs="+")
    s.set_defaults(handler=cmd_tag_add)
    s = vs.add_parser("remove", help="Detach tags (does not delete the item)")
    s.add_argument("key")
    s.add_argument("name", nargs="+")
    s.set_defaults(handler=cmd_tag_remove)
    s = vs.add_parser("list", help="An item's tags, or all library tags")
    s.add_argument("key", nargs="?")
    s.set_defaults(handler=cmd_tag_list)


def _pdf(sub: Any) -> None:
    pdf = sub.add_parser("pdf", help="Attachment files")
    vs = pdf.add_subparsers(dest="verb")
    s = vs.add_parser("attach", help="Attach a PDF to an existing item")
    s.add_argument("item")
    s.add_argument("--pdf", required=True)
    add_tag_opt(s)
    s.set_defaults(handler=cmd_pdf_attach)
    s = vs.add_parser("fetch", help="Download an item's PDF")
    s.add_argument("item")
    s.add_argument("--output", required=True)
    s.set_defaults(handler=cmd_pdf_fetch)
    s = vs.add_parser("replace", help="Replace an item's PDF file")
    s.add_argument("item")
    s.add_argument("--pdf", required=True)
    s.set_defaults(handler=cmd_pdf_replace)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zhost-cli", description="Manage a self-hosted Zotero (zhost)"
    )
    parser.add_argument("-j", "--json", action="store_true", dest="use_json", help="Output JSON")
    parser.add_argument("--config", help="Config JSON path")
    sub = parser.add_subparsers(dest="command")

    s = sub.add_parser("setup", help="Write config and check the API-key command")
    s.add_argument("--base-url", required=True)
    s.add_argument("--api-key-command", required=True)
    s.add_argument("--user-id", default="1")

    _item(sub)
    _collection(sub)
    _library(sub)
    _highlight(sub)
    _note(sub)
    _tag(sub)
    _pdf(sub)

    s = sub.add_parser("api", help="Call the zhost API directly")
    s.add_argument("method")
    s.add_argument("path")
    s.add_argument("--query", action="append", default=[], help="Query item KEY=VALUE")
    s.add_argument("--header", action="append", default=[], help="Header KEY=VALUE")
    s.add_argument("--body", help="JSON request body")
    s.add_argument("--file", help="JSON body file or - for stdin")
    s.set_defaults(handler=cmd_api)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    ns = parser.parse_args(argv)
    if not ns.command:
        parser.print_help()
        sys.exit(0)
    try:
        if ns.command == "setup":
            cmd_setup(ns)
            return
        handler = getattr(ns, "handler", None)
        if handler is None:
            # A noun with no verb: show that noun's help.
            parser.parse_args([ns.command, "--help"])
            return
        handler(make_client(ns.config), ns)
    except CLIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
