from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from zhost_cli.main import main


class State:
    version = 10
    collections: dict[str, dict[str, Any]] = {}
    items: dict[str, dict[str, Any]] = {}
    fulltext: dict[str, dict[str, Any]] = {}
    requests: list[dict[str, Any]] = []
    counter = 0


_ALPHA = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"  # Zotero key alphabet (no 0/1/O/L)


def _key(prefix: str) -> str:
    State.counter += 1
    n, s = State.counter, ""
    for _ in range(8):
        s, n = _ALPHA[n % 33] + s, n // 33
    return s


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def _send(self, status: int, body: Any, total: int | None = None) -> None:
        payload = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Last-Modified-Version", str(State.version))
        if total is not None:
            self.send_header("Total-Results", str(total))
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def _raw(self, status: int, body: bytes = b"") -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _written(self, key: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "successful": {"0": {"key": key, "version": State.version, "data": data}},
            "success": {},
            "unchanged": {},
            "failed": {},
        }

    def _rows(self, store: dict[str, dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
        return [
            {"key": k, "version": store[k].get("version", 1), "data": store[k]}
            for k in keys
            if k in store
        ]

    def _page(self, query: dict[str, list[str]], rows: list[dict[str, Any]]) -> None:
        """A Zotero-style page: slice by start/limit, report the full count."""
        start = int(query.get("start", ["0"])[0])
        limit = int(query.get("limit", ["100"])[0])
        self._send(200, rows[start : start + limit], total=len(rows))

    def _handle(self) -> None:
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        length = int(self.headers.get("content-length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        body: Any = json.loads(raw) if raw and raw[:1] in (b"[", b"{") else None
        State.requests.append({"method": self.command, "path": path, "query": query, "body": body})

        if path == "/users/1/collections":
            if self.command == "GET" and query.get("format") == ["versions"]:
                self._send(200, {k: v["version"] for k, v in State.collections.items()})
            elif self.command == "GET":
                self._send(200, self._rows(State.collections, query["collectionKey"][0].split(",")))
            elif self.command == "POST":
                State.version += 1
                key = body[0].get("key") or _key("COLL")  # honor client-supplied key (import)
                State.collections[key] = {**body[0], "key": key, "version": State.version}
                self._send(200, self._written(key, State.collections[key]))
            elif self.command == "PATCH":
                State.version += 1
                key = body[0]["key"]
                State.collections.setdefault(key, {"key": key}).update(body[0])
                self._send(200, self._written(key, State.collections[key]))
            elif self.command == "DELETE":
                for key in query.get("collectionKey", [""])[0].split(","):
                    State.collections.pop(key, None)
                self._raw(204)
            return

        coll_items = re.match(r"/users/1/collections/([^/]+)/items(/top)?$", path)
        if coll_items and self.command == "GET":
            ck = coll_items.group(1)
            keys = [
                k
                for k, v in State.items.items()
                if ck in (v.get("collections") or [])
                and not (coll_items.group(2) and "parentItem" in v)
            ]
            self._page(query, self._rows(State.items, keys))
            return

        fulltext = re.match(r"/users/1/items/([^/]+)/fulltext$", path)
        if fulltext:
            key = fulltext.group(1)
            if self.command == "GET":
                ft = State.fulltext.get(key)
                self._send(404, {"message": "no fulltext"}) if ft is None else self._send(200, ft)
            else:  # POST/PUT stores the index
                State.fulltext[key] = body
                self._raw(204)
            return

        if path in ("/users/1/items/top", "/users/1/items/trash") and self.command == "GET":
            top = path.endswith("/top")
            keys = [
                k
                for k, v in State.items.items()
                if (("parentItem" not in v) if top else v.get("deleted"))
            ]
            self._page(query, self._rows(State.items, keys))
            return

        if path == "/users/1/items":
            if self.command == "POST":
                State.version += 1
                key = body[0].get("key") or _key("ITEM")  # honor client-supplied key (import)
                State.items[key] = {**body[0], "key": key, "version": State.version}
                self._send(200, self._written(key, State.items[key]))
            elif self.command == "PATCH":
                State.version += 1
                key = body[0]["key"]
                State.items.setdefault(key, {"key": key}).update(body[0])
                self._send(200, self._written(key, State.items[key]))
            elif self.command == "DELETE":
                for key in query.get("itemKey", [""])[0].split(","):
                    State.items.pop(key, None)
                self._raw(204)
            elif "itemKey" in query:
                self._send(200, self._rows(State.items, query["itemKey"][0].split(",")))
            else:
                self._page(query, self._rows(State.items, list(State.items)))
            return

        if path == "/users/1/tags" and self.command == "GET":
            self._send(200, [{"tag": "crispr", "numItems": 1}])
            return

        if path.endswith("/file"):
            key = path.split("/")[-2]
            if self.command == "GET":
                self.send_response(302)
                self.send_header("Location", f"http://{self.headers['Host']}/blob/{key}")
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif b"upload=" in raw:
                self._raw(204)
            else:
                State.requests[-1]["form"] = parse_qs(raw.decode())
                host = self.headers["Host"]
                self._send(
                    200,
                    {
                        "url": f"http://{host}/uploads/T",
                        "uploadKey": "T",
                        "prefix": "",
                        "suffix": "",
                    },
                )
            return
        if path.startswith("/uploads/"):
            self._raw(201)
            return
        if path.startswith("/blob/"):
            self._raw(200, b"%PDF-1.7 fake")
            return

        self._send(404, {"message": "not found"})


@pytest.fixture()
def server(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    State.version, State.collections, State.items, State.requests, State.counter = 10, {}, {}, [], 0
    State.fulltext = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    monkeypatch.setenv("ZHOST_BASE_URL", base)
    monkeypatch.setenv("ZHOST_API_KEY", "test-key")
    monkeypatch.setenv("ZHOST_USER_ID", "1")
    try:
        yield base
    finally:
        httpd.shutdown()


def _reqs(method: str, path: str) -> list[dict[str, Any]]:
    return [r for r in State.requests if r["method"] == method and r["path"] == path]


# -- item -----------------------------------------------------------------


def test_item_add(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    main(["item", "add", "--title", "P", "--author", "Jane Roe", "--tag", "llm-picked"])
    key = capsys.readouterr().out.strip()
    assert key in State.items
    post = _reqs("POST", "/users/1/items")[0]
    assert post["body"][0]["tags"] == [{"tag": "llm-picked", "type": 1}]
    assert post["body"][0]["creators"][0]["lastName"] == "Roe"


def test_item_add_ensures_collection(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    main(["item", "add", "--title", "A", "--collection", "Inbox"])
    main(["item", "add", "--title", "B", "--collection", "Inbox"])
    assert len(_reqs("POST", "/users/1/collections")) == 1  # idempotent
    coll = next(iter(State.collections))
    assert all(p["body"][0]["collections"] == [coll] for p in _reqs("POST", "/users/1/items"))


def test_item_find_resolves_papers(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    State.items["PAPER222"] = {"key": "PAPER222", "itemType": "journalArticle", "title": "P"}
    State.items["ATTAC222"] = {
        "key": "ATTAC222",
        "itemType": "attachment",
        "parentItem": "PAPER222",
    }
    main(["-j", "item", "find", "x"])
    assert {i["key"] for i in json.loads(capsys.readouterr().out)} == {"PAPER222"}
    q = [r for r in _reqs("GET", "/users/1/items") if "q" in r["query"]][0]
    assert q["query"]["qmode"] == ["everything"]


def test_item_move(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    State.items["PAPER222"] = {"key": "PAPER222", "itemType": "journalArticle"}
    main(["item", "move", "PAPER222", "--collection", "Aptamers"])
    coll = next(iter(State.collections))  # created by ensure
    patch = _reqs("PATCH", "/users/1/items")[0]
    assert patch["body"][0] == {"key": "PAPER222", "collections": [coll]}


def test_item_remove_requires_yes(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["item", "remove", "PAPER222"])
    assert "requires --yes" in capsys.readouterr().err


def test_invalid_key_rejected(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["item", "get", "bad-key"])
    assert "invalid object key" in capsys.readouterr().err


# -- collection -----------------------------------------------------------


def test_collection_create_rename_move_remove(
    server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["collection", "create", "Folder"])
    key = capsys.readouterr().out.strip()
    assert State.collections[key]["name"] == "Folder"

    main(["collection", "rename", key, "Renamed"])
    assert State.collections[key]["name"] == "Renamed"

    main(["collection", "move", key, "--top"])
    assert State.collections[key]["parentCollection"] is False

    main(["collection", "remove", key, "--yes"])
    assert key not in State.collections


def test_collection_list_tree(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    State.collections["PARENT22"] = {"key": "PARENT22", "name": "Top", "version": 1}
    State.collections["CHDREN22"] = {
        "key": "CHDREN22",
        "name": "Sub",
        "parentCollection": "PARENT22",
        "version": 1,
    }
    main(["collection", "list"])
    out = capsys.readouterr().out
    assert "Top" in out and "  CHDREN22  Sub" in out  # child indented under parent


def test_collection_items(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    State.items["PAPER222"] = {
        "key": "PAPER222",
        "itemType": "journalArticle",
        "collections": ["FNDR2222"],
    }
    main(["collection", "items", "FNDR2222"])
    assert "PAPER222" in capsys.readouterr().out


# -- tag / note / highlight / pdf -----------------------------------------


def test_tag_add_remove(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    State.items["PAPER222"] = {
        "key": "PAPER222",
        "itemType": "journalArticle",
        "tags": [{"tag": "keep", "type": 0}, {"tag": "drop", "type": 1}],
    }
    main(["tag", "add", "PAPER222", "new"])
    main(["tag", "remove", "PAPER222", "drop"])
    names = {t["tag"] for t in State.items["PAPER222"]["tags"]}
    assert names == {"keep", "new"}


def test_note_add_and_list(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    State.items["PAPER222"] = {"key": "PAPER222", "itemType": "journalArticle"}
    main(["note", "add", "PAPER222", "--text", "<p>hi</p>"])
    note = [r for r in _reqs("POST", "/users/1/items") if r["body"][0]["itemType"] == "note"][0]
    assert note["body"][0]["parentItem"] == "PAPER222"
    main(["note", "list", "PAPER222"])
    assert "note" in capsys.readouterr().out


def test_pdf_attach_and_fetch(
    server: str, tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf = f"{tmp_path}/p.pdf"
    open(pdf, "wb").write(b"%PDF-1.7 data")
    State.items["PAPER222"] = {"key": "PAPER222", "itemType": "journalArticle"}
    main(["pdf", "attach", "PAPER222", "--pdf", pdf])
    assert any(r["path"].startswith("/uploads/") for r in State.requests)
    # the attachment was created under the paper
    att = [r for r in _reqs("POST", "/users/1/items") if r["body"][0]["itemType"] == "attachment"][
        0
    ]
    assert att["body"][0]["parentItem"] == "PAPER222"
    out_path = f"{tmp_path}/dl.pdf"
    main(["pdf", "fetch", "PAPER222", "--output", out_path])
    assert open(out_path, "rb").read().startswith(b"%PDF")


def test_highlight_resolves_pdf_child(
    server: str, tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    import fitz  # type: ignore[import-untyped]

    pdf = f"{tmp_path}/p.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 60), "highlight this sentence", fontsize=11)
    doc.save(pdf)
    doc.close()
    State.items["PAPER222"] = {"key": "PAPER222", "itemType": "journalArticle"}
    State.items["ATTAC222"] = {
        "key": "ATTAC222",
        "itemType": "attachment",
        "parentItem": "PAPER222",
        "contentType": "application/pdf",
    }
    main(["highlight", "add", "PAPER222", "--pdf", pdf, "--text", "highlight this"])
    ann = [r for r in _reqs("POST", "/users/1/items") if r["body"][0]["itemType"] == "annotation"][
        0
    ]
    assert ann["body"][0]["parentItem"] == "ATTAC222"
    assert ann["body"][0]["annotationText"] == "highlight this"


def test_api_escape_hatch(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    main(["api", "GET", "/users/1/tags"])
    assert json.loads(capsys.readouterr().out) == [{"tag": "crispr", "numItems": 1}]


def test_item_get_children(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    State.items["PAPER222"] = {"key": "PAPER222", "itemType": "journalArticle", "title": "P"}
    State.items["NOTE2222"] = {"key": "NOTE2222", "itemType": "note", "parentItem": "PAPER222"}
    main(["item", "get", "PAPER222"])
    out = capsys.readouterr().out
    assert "PAPER222" in out and "NOTE2222" in out


def test_item_edit(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    State.items["PAPER222"] = {"key": "PAPER222", "itemType": "journalArticle", "title": "old"}
    main(["item", "edit", "PAPER222", "--set", "title=new"])
    patch = _reqs("PATCH", "/users/1/items")[0]
    assert patch["body"][0] == {"title": "new", "key": "PAPER222"}


def test_item_add_with_pdf(
    server: str, tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf = f"{tmp_path}/p.pdf"
    open(pdf, "wb").write(b"%PDF-1.7 data")
    main(["-j", "item", "add", "--title", "P", "--pdf", pdf])
    out = json.loads(capsys.readouterr().out)
    assert out["item"] in State.items and "attachment" in out
    assert any(r.get("form", {}).get("filename") == ["p.pdf"] for r in State.requests)
    assert any(r["path"].startswith("/uploads/") for r in State.requests)


def test_tag_list(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    State.items["PAPER222"] = {
        "key": "PAPER222",
        "itemType": "journalArticle",
        "tags": [{"tag": "a", "type": 1}],
    }
    main(["-j", "tag", "list", "PAPER222"])
    assert json.loads(capsys.readouterr().out) == [{"tag": "a", "type": 1}]
    main(["-j", "tag", "list"])  # whole-library tags
    assert json.loads(capsys.readouterr().out) == [{"tag": "crispr", "numItems": 1}]


def test_highlight_list(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    State.items["PAPER222"] = {"key": "PAPER222", "itemType": "journalArticle"}
    State.items["ATTAC222"] = {
        "key": "ATTAC222",
        "itemType": "attachment",
        "parentItem": "PAPER222",
        "contentType": "application/pdf",
    }
    State.items["ANNT2222"] = {
        "key": "ANNT2222",
        "itemType": "annotation",
        "parentItem": "ATTAC222",
        "annotationText": "x",
        "annotationColor": "#ff0",
    }
    main(["highlight", "list", "PAPER222"])
    assert "ANNT2222" in capsys.readouterr().out


def test_pdf_replace(server: str, tmp_path: object, capsys: pytest.CaptureFixture[str]) -> None:
    pdf = f"{tmp_path}/p.pdf"
    open(pdf, "wb").write(b"%PDF-1.7 new")
    State.items["PAPER222"] = {"key": "PAPER222", "itemType": "journalArticle"}
    State.items["ATTAC222"] = {
        "key": "ATTAC222",
        "itemType": "attachment",
        "parentItem": "PAPER222",
        "contentType": "application/pdf",
        "md5": "oldmd5",
    }
    main(["pdf", "replace", "PAPER222", "--pdf", pdf])
    assert any(r["path"].startswith("/uploads/") for r in State.requests)


def test_collection_move_parent(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    State.collections["PARENT22"] = {"key": "PARENT22", "name": "P", "version": 1}
    State.collections["CHDREN22"] = {"key": "CHDREN22", "name": "C", "version": 1}
    main(["collection", "move", "CHDREN22", "--parent", "PARENT22"])
    patch = _reqs("PATCH", "/users/1/collections")[0]
    assert patch["body"][0] == {"key": "CHDREN22", "parentCollection": "PARENT22"}


# -- bulk: item list / library export / import ----------------------------


def _seed_library() -> None:
    """A small library: one project collection, a paper with a PDF attachment
    (with fulltext) and a note child."""
    State.collections["FOLDER22"] = {"key": "FOLDER22", "name": "Proj", "version": 3}
    State.items["PAPER222"] = {
        "key": "PAPER222",
        "itemType": "journalArticle",
        "title": "P",
        "DOI": "10.1/x",
        "collections": ["FOLDER22"],
        "tags": [{"tag": "rna", "type": 1}],
    }
    State.items["ATTAC222"] = {
        "key": "ATTAC222",
        "itemType": "attachment",
        "parentItem": "PAPER222",
        "contentType": "application/pdf",
        "filename": "p.pdf",
        "md5": "abc",
    }
    State.items["NOTE2222"] = {"key": "NOTE2222", "itemType": "note", "parentItem": "PAPER222"}
    State.fulltext["ATTAC222"] = {"content": "full body", "indexedChars": 9, "totalChars": 9}


def test_item_list_top_lossless(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_library()
    main(["-j", "item", "list"])
    rows = json.loads(capsys.readouterr().out)
    assert {r["key"] for r in rows} == {"PAPER222"}  # top-level only
    assert rows[0]["data"]["DOI"] == "10.1/x"  # full data preserved


def test_item_list_all_includes_children(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_library()
    main(["-j", "item", "list", "--all"])
    rows = json.loads(capsys.readouterr().out)
    assert {r["key"] for r in rows} == {"PAPER222", "ATTAC222", "NOTE2222"}


def test_item_list_collection_scope(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_library()
    State.items["OTHER222"] = {"key": "OTHER222", "itemType": "journalArticle", "title": "Q"}
    main(["-j", "item", "list", "--collection", "Proj"])
    rows = json.loads(capsys.readouterr().out)
    assert {r["key"] for r in rows} == {"PAPER222"}


def test_item_list_pages_all_results(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    for i in range(120):
        k = f"IT{i:06d}"
        State.items[k] = {"key": k, "itemType": "journalArticle"}
    main(["-j", "item", "list"])
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 120  # nothing dropped at the 100-item page boundary
    assert len(_reqs("GET", "/users/1/items/top")) >= 2  # actually paged


def test_library_export(server: str, tmp_path: object, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_library()
    out = f"{tmp_path}/dump"
    main(["library", "export", out])

    manifest = json.loads(open(f"{out}/manifest.json").read())
    assert manifest["counts"]["items"] == 1  # one top-level paper

    rec = json.loads(open(f"{out}/items/PAPER222.json").read())
    assert rec["item"]["data"]["title"] == "P"
    assert {c["key"] for c in rec["children"]} == {"ATTAC222", "NOTE2222"}
    assert rec["fulltext"]["ATTAC222"]["content"] == "full body"

    assert open(f"{out}/files/ATTAC222/p.pdf", "rb").read().startswith(b"%PDF")
    colls = json.loads(open(f"{out}/collections.json").read())
    assert any(c["key"] == "FOLDER22" for c in colls)


def test_library_export_no_files(
    server: str, tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_library()
    out = f"{tmp_path}/dump"
    main(["library", "export", out, "--no-files"])
    assert not os.path.exists(f"{out}/files")
    # metadata still complete
    assert os.path.exists(f"{out}/items/PAPER222.json")


def test_library_roundtrip(
    server: str, tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_library()
    out = f"{tmp_path}/dump"
    main(["library", "export", out])

    State.collections, State.items, State.fulltext = {}, {}, {}  # wipe, then restore
    main(["library", "import", out])

    assert any(c.get("name") == "Proj" for c in State.collections.values())
    assert State.items["PAPER222"]["title"] == "P"  # key preserved
    assert State.items["NOTE2222"]["parentItem"] == "PAPER222"  # child re-parented
    assert State.fulltext["ATTAC222"]["content"] == "full body"  # index restored
    assert any(r["path"].startswith("/uploads/") for r in State.requests)  # file re-uploaded
