from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any

import pytest

from vikunja_cli.client import Client
from vikunja_cli.errors import APIError


class Handler(BaseHTTPRequestHandler):
    response_status = 200
    response_body: Any = {"ok": True}
    seen: dict[str, Any] = {}

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode() if length else ""
        Handler.seen = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": json.loads(body) if body else None,
        }
        encoded = json.dumps(Handler.response_body).encode()
        self.send_response(Handler.response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@pytest.fixture
def server() -> str:
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
