from __future__ import annotations

import json
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from vikunja_cli.client import Client
from vikunja_cli.errors import APIError


class Handler(BaseHTTPRequestHandler):
    response_status = 200
    response_body: Any = {"ok": True}
    response_content_type = "application/json"
    seen: dict[str, Any] = {}

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def do_PUT(self) -> None:  # noqa: N802
        self._handle()

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b""
        content_type = self.headers.get("Content-Type", "")
        Handler.seen = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": json.loads(raw_body.decode()) if raw_body and _is_json(content_type) else None,
        }
        if raw_body and not _is_json(content_type):
            Handler.seen["content_type"] = content_type
            Handler.seen["raw_body"] = raw_body
        encoded = (
            Handler.response_body
            if isinstance(Handler.response_body, bytes)
            else json.dumps(Handler.response_body).encode()
        )
        self.send_response(Handler.response_status)
        self.send_header("Content-Type", Handler.response_content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def _is_json(content_type: str) -> bool:
    return content_type.partition(";")[0].lower() == "application/json"


@pytest.fixture
def server() -> Generator[str]:
    Handler.response_status = 200
    Handler.response_body = {"ok": True}
    Handler.response_content_type = "application/json"
    Handler.seen = {}
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join()


def test_client_adds_api_prefix_and_bearer_header(server: str) -> None:
    Handler.response_status = 200
    Handler.response_body = {"ok": True}
    client = Client(server, "secret")

    assert client.post("/tasks/1", {"done": True}) == {"ok": True}
    assert Handler.seen == {
        "path": "/api/v1/tasks/1",
        "authorization": "Bearer secret",
        "body": {"done": True},
    }


def test_client_encodes_repeated_query_values(server: str) -> None:
    Handler.response_status = 200
    Handler.response_body = []
    client = Client(server, "secret")

    client.get("/tasks", {"sort_by": ["due_date", "priority"], "s": "foo bar"})

    assert Handler.seen["path"] == "/api/v1/tasks?sort_by=due_date&sort_by=priority&s=foo+bar"


def test_client_raises_api_error(server: str) -> None:
    Handler.response_status = 403
    Handler.response_body = {"message": "nope"}
    client = Client(server, "secret")

    with pytest.raises(APIError, match="nope"):
        client.get("/forbidden")


def test_client_uploads_multiple_attachments_with_files_field(server: str, tmp_path: Path) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "two.bin"
    first.write_text("one")
    second.write_bytes(b"two")
    Handler.response_body = {"message": "uploaded"}
    client = Client(server, "secret")

    assert client.upload_task_attachments(123, [first, second]) == {"message": "uploaded"}

    raw = Handler.seen["raw_body"]
    assert Handler.seen["path"] == "/api/v1/tasks/123/attachments"
    assert Handler.seen["content_type"].startswith("multipart/form-data; boundary=")
    assert raw.count(b'name="files"') == 2
    assert b'filename="one.txt"' in raw
    assert b'filename="two.bin"' in raw
    assert b"\r\none\r\n" in raw
    assert b"\r\ntwo\r\n" in raw


def test_client_downloads_attachment_bytes(server: str) -> None:
    Handler.response_body = b"payload"
    Handler.response_content_type = "application/octet-stream"
    client = Client(server, "secret")

    assert client.download_task_attachment(7, 8) == b"payload"
    assert Handler.seen["path"] == "/api/v1/tasks/7/attachments/8"
