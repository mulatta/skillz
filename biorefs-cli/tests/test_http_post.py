from __future__ import annotations

import json

from biorefs_cli.http import HttpClient, HttpResponse


class PostEchoHttpClient(HttpClient):
    """Capture the (method, body) of every ``_once`` call and echo JSON back."""

    def __init__(self) -> None:
        super().__init__(timeout_seconds=3)
        self.calls: list[tuple[str, bytes | None]] = []

    def _once(
        self, method: str, url: str, *, body: bytes | None, headers: dict[str, str]
    ) -> HttpResponse:
        assert headers is not None
        self.calls.append((method, body))
        return HttpResponse(status=200, headers={}, body=b'{"ok": true}')


class PostRedirectHttpClient(HttpClient):
    """Answer the first POST with a redirect, then echo the follow-up request."""

    def __init__(self, *, status: int) -> None:
        super().__init__(timeout_seconds=3)
        self.status = status
        self.calls: list[tuple[str, str, bytes | None]] = []

    def _once(
        self, method: str, url: str, *, body: bytes | None, headers: dict[str, str]
    ) -> HttpResponse:
        assert headers is not None
        self.calls.append((method, url, body))
        if len(self.calls) == 1:
            return HttpResponse(
                status=self.status,
                headers={"location": "https://example.org/result"},
                body=b"",
            )
        return HttpResponse(status=200, headers={}, body=b'{"ok": true}')


def test_post_json_sends_body_and_parses_object() -> None:
    client = PostEchoHttpClient()

    result = client.post_json("https://example.org/graphql", {"query": "{x}"})

    assert result == {"ok": True}
    assert len(client.calls) == 1
    method, body = client.calls[0]
    assert method == "POST"
    assert body is not None
    assert json.loads(body) == {"query": "{x}"}


def test_post_303_redirect_becomes_bodyless_get() -> None:
    client = PostRedirectHttpClient(status=303)

    result = client.post_json("https://example.org/graphql", {"query": "{x}"})

    assert result == {"ok": True}
    assert [(method, body) for method, _url, body in client.calls] == [
        ("POST", json.dumps({"query": "{x}"}).encode("utf-8")),
        ("GET", None),
    ]
    assert client.calls[1][1] == "https://example.org/result"


def test_post_302_redirect_becomes_bodyless_get() -> None:
    client = PostRedirectHttpClient(status=302)

    result = client.post_json("https://example.org/graphql", {"query": "{x}"})

    assert result == {"ok": True}
    assert [method for method, _url, _body in client.calls] == ["POST", "GET"]
    assert client.calls[1][2] is None
