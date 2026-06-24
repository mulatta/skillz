from __future__ import annotations

import json

import pytest
from biorefs_cli.errors import HTTPError
from biorefs_cli.http import HttpClient, HttpResponse, RetryPolicy


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


class PostKeepRedirectHttpClient(HttpClient):
    """307/308: the follow-up must keep the original method AND body."""

    def __init__(self, *, status: int) -> None:
        super().__init__(timeout_seconds=3)
        self.status = status
        self.calls: list[tuple[str, bytes | None]] = []

    def _once(
        self, method: str, url: str, *, body: bytes | None, headers: dict[str, str]
    ) -> HttpResponse:
        self.calls.append((method, body))
        if len(self.calls) == 1:
            return HttpResponse(
                status=self.status,
                headers={"location": "https://example.org/result"},
                body=b"",
            )
        return HttpResponse(status=200, headers={}, body=b'{"ok": true}')


@pytest.mark.parametrize("status", [307, 308])
def test_post_307_308_preserve_method_and_body(status: int) -> None:
    client = PostKeepRedirectHttpClient(status=status)

    client.post_json("https://example.org/graphql", {"query": "{x}"})

    body = json.dumps({"query": "{x}"}).encode("utf-8")
    assert client.calls == [("POST", body), ("POST", body)]


class HeaderCapturingRedirectHttpClient(HttpClient):
    """Capture per-hop headers to confirm Content-Type is dropped on POST->GET."""

    def __init__(self) -> None:
        super().__init__(timeout_seconds=3)
        self.header_hops: list[dict[str, str]] = []

    def _once(
        self, method: str, url: str, *, body: bytes | None, headers: dict[str, str]
    ) -> HttpResponse:
        self.header_hops.append(dict(headers))
        if len(self.header_hops) == 1:
            return HttpResponse(
                status=303, headers={"location": "https://example.org/x"}, body=b""
            )
        return HttpResponse(status=200, headers={}, body=b'{"ok": true}')


def test_post_to_get_redirect_drops_content_type() -> None:
    client = HeaderCapturingRedirectHttpClient()

    client.post_json("https://example.org/graphql", {"query": "{x}"})

    assert client.header_hops[0]["Content-Type"] == "application/json"
    assert "Content-Type" not in client.header_hops[1]


class StatusHttpClient(HttpClient):
    """Always answer with a fixed status; count attempts."""

    def __init__(self, *, status: int) -> None:
        super().__init__(timeout_seconds=3, retry_policy=RetryPolicy(attempts=3))
        self.status = status
        self.attempts = 0

    def _once(
        self, method: str, url: str, *, body: bytes | None, headers: dict[str, str]
    ) -> HttpResponse:
        self.attempts += 1
        return HttpResponse(status=self.status, headers={}, body=b"")

    def _sleep(self, attempt: int, retry_after_seconds: float | None) -> None:
        pass


def test_non_idempotent_post_not_retried_when_retry_transient_false() -> None:
    client = StatusHttpClient(status=500)

    with pytest.raises(HTTPError):
        client.post_json("https://example.org/graphql", {"q": 1}, retry_transient=False)

    assert client.attempts == 1


def test_204_no_content_decodes_to_empty_object() -> None:
    class NoContentClient(HttpClient):
        def __init__(self) -> None:
            super().__init__(timeout_seconds=3)

        def _once(
            self, method: str, url: str, *, body: bytes | None, headers: dict[str, str]
        ) -> HttpResponse:
            return HttpResponse(status=204, headers={}, body=b"")

    result = NoContentClient().post_json("https://example.org/q", {"q": 1})
    assert result == {}
