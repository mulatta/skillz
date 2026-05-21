from __future__ import annotations

import json
import stat
from typing import TYPE_CHECKING

import pytest
from biorefs_cli.config import (
    Config,
    check_configured_secrets,
    config_to_public_dict,
    load_config,
    merge_config,
    run_secret_command,
    write_config,
)
from biorefs_cli.errors import (
    ConfigError,
    CredentialCheckError,
    HTTPError,
    RateLimitError,
)
from biorefs_cli.http import HttpClient, HttpResponse, RetryPolicy
from biorefs_cli.output import escape_cell, markdown_heading, markdown_table, print_json
from biorefs_cli.rate_limit import RateLimitPolicy

if TYPE_CHECKING:
    from pathlib import Path


class SequenceHttpClient(HttpClient):
    def __init__(self, responses: list[HttpResponse], *, attempts: int = 3) -> None:
        super().__init__(
            timeout_seconds=3,
            retry_policy=RetryPolicy(attempts=attempts, base_delay_seconds=0.1),
        )
        self.responses = responses
        self.urls: list[str] = []
        self.sleeps: list[tuple[int, float | None]] = []

    def _get_once(self, url: str, *, headers: dict[str, str]) -> HttpResponse:
        assert headers is not None
        self.urls.append(url)
        return self.responses.pop(0)

    def _sleep(self, attempt: int, retry_after_seconds: float | None) -> None:
        self.sleeps.append((attempt, retry_after_seconds))


class NetworkFailHttpClient(HttpClient):
    def __init__(self) -> None:
        super().__init__(timeout_seconds=3, retry_policy=RetryPolicy(attempts=2))
        self.sleeps: list[tuple[int, float | None]] = []

    def _get_once(self, url: str, *, headers: dict[str, str]) -> HttpResponse:
        assert url.startswith("https://")
        assert headers is not None
        raise OSError

    def _sleep(self, attempt: int, retry_after_seconds: float | None) -> None:
        self.sleeps.append((attempt, retry_after_seconds))


class RedirectLoopHttpClient(HttpClient):
    def __init__(self) -> None:
        super().__init__(timeout_seconds=3)

    def _get_once(self, url: str, *, headers: dict[str, str]) -> HttpResponse:
        assert headers is not None
        return HttpResponse(status=302, headers={"location": url}, body=b"")


def response(
    body: bytes, *, status: int = 200, headers: dict[str, str] | None = None
) -> HttpResponse:
    return HttpResponse(status=status, headers=headers or {}, body=body)


def test_config_rejects_invalid_shapes_and_types(tmp_path: Path) -> None:
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    array_json = tmp_path / "array.json"
    array_json.write_text("[]", encoding="utf-8")

    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(invalid_json)
    with pytest.raises(ConfigError, match="root must be"):
        load_config(array_json)
    with pytest.raises(ConfigError, match="timeout_seconds"):
        Config.from_mapping({"timeout_seconds": 0})
    with pytest.raises(ConfigError, match="email must be"):
        Config.from_mapping({"email": 1})


def test_config_write_merge_public_dict_and_secret_checks(tmp_path: Path) -> None:
    path = write_config(
        Config(email="user@example.org", timeout_seconds=3),
        tmp_path / "config" / "config.json",
    )
    merged = merge_config(load_config(path), {"ncbi_api_key_command": "printf secret"})

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert merged.email == "user@example.org"
    assert merged.ncbi_api_key_command == "printf secret"
    assert config_to_public_dict(merged)["email"] == "user@example.org"
    assert run_secret_command("printf secret", timeout_seconds=3) == "secret"
    assert check_configured_secrets(merged)[0].name == "ncbi_api_key_command"
    with pytest.raises(CredentialCheckError, match="empty stdout"):
        run_secret_command("true", timeout_seconds=3)


def test_output_helpers_escape_and_render(capsys: pytest.CaptureFixture[str]) -> None:
    print_json({"b": 2, "a": 1})
    captured = capsys.readouterr().out

    assert captured.startswith('{\n  "a": 1,')
    assert markdown_heading("Title", level=3) == "### Title"
    assert escape_cell("a|b\nc") == "a\\|b c"
    assert markdown_table(("A", "B"), [("x|y", "z\nw")]) == (
        "| A | B |\n| --- | --- |\n| x\\|y | z w |"
    )


def test_http_json_error_and_status_paths() -> None:
    invalid = SequenceHttpClient([response(b"not-json")])
    non_object = SequenceHttpClient([response(b"[]")])
    not_found = SequenceHttpClient([response(b"missing", status=404)])

    with pytest.raises(HTTPError, match="invalid JSON"):
        invalid.get_json("https://example.org/data")
    with pytest.raises(HTTPError, match="non-object JSON"):
        non_object.get_json("https://example.org/data")
    with pytest.raises(HTTPError, match="HTTP 404"):
        not_found.get("https://example.org/data")


def test_http_transient_retry_network_failure_and_redirect_limit() -> None:
    transient = SequenceHttpClient(
        [response(b"error", status=500), response(json.dumps({"ok": True}).encode())]
    )
    network = NetworkFailHttpClient()

    assert transient.get_json("https://example.org/data") == {"ok": True}
    assert transient.sleeps == [(0, None)]
    with pytest.raises(HTTPError, match="network request failed"):
        network.get("https://example.org/data")
    assert network.sleeps == [(0, None), (1, None)]
    with pytest.raises(HTTPError, match="too many redirects"):
        RedirectLoopHttpClient().get("https://example.org/loop")


def test_http_rate_limit_and_invalid_url_paths() -> None:
    limited = SequenceHttpClient(
        [response(b"limited", status=429, headers={"retry-after": "2"})], attempts=1
    )

    with pytest.raises(RateLimitError) as exc_info:
        limited.get("https://example.org/data")
    assert exc_info.value.retry_after_seconds == 2.0
    with pytest.raises(HTTPError, match="URL must use https"):
        HttpClient(timeout_seconds=3).get("http://example.org/data")


def test_type_imports_are_runtime_lightweight() -> None:
    policy = RateLimitPolicy(name="test", rules=())

    assert policy.name == "test"
