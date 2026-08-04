# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from linkwarden_cli.main import main


class State:
    requests: list[dict[str, Any]] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        self.handle_request()

    def do_POST(self) -> None:
        self.handle_request()

    def do_PUT(self) -> None:
        self.handle_request()

    def do_DELETE(self) -> None:
        self.handle_request()

    def handle_request(self) -> None:
        parsed = urlparse(self.path)
        raw = self.rfile.read(int(self.headers.get("content-length", "0") or "0"))
        body = json.loads(raw.decode()) if raw else None
        State.requests.append(
            {
                "method": self.command,
                "path": parsed.path,
                "query": parse_qs(parsed.query),
                "auth": self.headers.get("Authorization"),
                "body": body,
            }
        )
        response: Any = {"response": "ok"}
        if parsed.path == "/api/v1/search":
            response = {
                "data": {
                    "links": [
                        {"id": 5, "name": "Example", "url": "https://example.com"}
                    ],
                    "nextCursor": 55,
                },
                "success": True,
            }
        elif parsed.path == "/api/v1/links" and self.command == "POST":
            response = {"response": {"id": 7, **(body or {})}}
        elif parsed.path == "/api/v1/links/7":
            response = {
                "response": {
                    "id": 7,
                    "name": "Example",
                    "url": "https://example.com",
                    "description": None,
                    "collection": {"id": 1, "ownerId": 9, "name": "Inbox"},
                    "tags": [{"name": "old"}],
                }
            }
        elif parsed.path == "/api/v1/collections":
            response = {"response": [{"id": 1, "name": "Inbox", "ownerId": 9}]}
        elif parsed.path == "/api/v1/collections/1":
            response = {
                "response": {"id": 1, "name": "Inbox", "ownerId": 9, "members": []}
            }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())


@pytest.fixture
def server() -> Generator[tuple[str, int]]:
    State.requests = []
    host = "127.0.0.1"
    httpd = ThreadingHTTPServer((host, 0), Handler)
    port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield host, port
    httpd.shutdown()


def run_cli(
    server: tuple[str, int], argv: list[str], capsys: pytest.CaptureFixture[str]
) -> str:
    host, port = server
    env = {"LINKWARDEN_BASE_URL": f"http://{host}:{port}", "LINKWARDEN_TOKEN": "secret"}
    with patch.dict("os.environ", env, clear=False):
        main(argv)
    return capsys.readouterr().out


def test_setup_writes_config_and_checks_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"

    main(
        [
            "--config",
            str(config),
            "setup",
            "--base-url",
            "https://linkwarden.example.com/",
            "--token-command",
            "printf test-token",
        ]
    )

    assert json.loads(config.read_text()) == {
        "base_url": "https://linkwarden.example.com",
        "token_command": "printf test-token",
    }
    out = capsys.readouterr().out
    assert f"Wrote {config}" in out
    assert "Token command works" in out
    assert "test-token" not in out


def test_search_uses_full_text_query(
    server: tuple[str, int], capsys: pytest.CaptureFixture[str]
) -> None:
    out = run_cli(server, ["link", "search", "tag:nix after:2026-01-01"], capsys)

    assert "Example" in out
    req = State.requests[-1]
    assert req["auth"] == "Bearer secret"
    assert req["path"] == "/api/v1/search"
    assert req["query"]["searchQueryString"] == ["tag:nix after:2026-01-01"]


def test_create_link_payload(
    server: tuple[str, int], capsys: pytest.CaptureFixture[str]
) -> None:
    run_cli(
        server,
        [
            "link",
            "create",
            "https://example.com",
            "--name",
            "Example",
            "--tag",
            "nix",
            "--collection",
            "Inbox",
        ],
        capsys,
    )

    req = State.requests[-1]
    assert req["method"] == "POST"
    assert req["path"] == "/api/v1/links"
    assert req["body"] == {
        "url": "https://example.com",
        "type": "url",
        "name": "Example",
        "collection": {"id": 1, "name": "Inbox"},
        "tags": [{"name": "nix"}],
    }


def test_create_link_requires_existing_collection(
    server: tuple[str, int], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        run_cli(
            server,
            [
                "link",
                "create",
                "https://example.com",
                "--collection",
                "Missing",
            ],
            capsys,
        )

    err = capsys.readouterr().err
    assert exc.value.code == 1
    assert "collection not found: Missing" in err
    assert [req["path"] for req in State.requests] == ["/api/v1/collections"]


def test_delete_requires_yes(
    server: tuple[str, int], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        run_cli(server, ["link", "delete", "7"], capsys)

    assert exc.value.code == 1
    assert State.requests == []


def test_api_escape_hatch(
    server: tuple[str, int], capsys: pytest.CaptureFixture[str]
) -> None:
    out = run_cli(
        server, ["api", "GET", "/api/v1/collections", "--query", "x=1"], capsys
    )

    assert "Inbox" in out
    req = State.requests[-1]
    assert req["path"] == "/api/v1/collections"
    assert req["query"] == {"x": ["1"]}
