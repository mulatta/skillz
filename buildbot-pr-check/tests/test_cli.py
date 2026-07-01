"""End-to-end tests for the CLI with the forge and Nixbot layers stubbed."""

from __future__ import annotations

import json

import pytest

from buildbot_pr_check import cli, github_api
from buildbot_pr_check.nixbot_api import NixbotClient

PR_URL = "https://github.com/mulatta/dots/pull/235"
HEAD_SHA = "280478056c6614a0cdbf7dc4a4b92fbdc2527807"
NIXBOT_WEB_URL = "https://buildbot.sjanglab.org/repos/github/mulatta/dots/builds/3"


def _run(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert isinstance(exc.value.code, int)
    return exc.value.code


@pytest.fixture
def stub_nixbot(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_nixbot_get(self: NixbotClient, path: str) -> dict[str, object]:
        assert path == "repos/github/mulatta/dots/builds/3"
        return {
            "build": {
                "id": 18,
                "number": 3,
                "status": "failed",
                "branch": "main",
                "commit_sha": HEAD_SHA,
                "error": None,
            },
            "attributes": [
                {
                    "id": 1,
                    "build_id": 18,
                    "attr": "x86_64-linux.nixos-taps",
                    "status": "failed",
                    "cached": False,
                    "error": "boom",
                },
                {
                    "id": 2,
                    "build_id": 18,
                    "attr": "x86_64-linux.treefmt",
                    "status": "succeeded",
                    "cached": True,
                    "error": None,
                },
            ],
        }

    monkeypatch.setattr(github_api, "get_pr_head_sha", lambda *a, **k: HEAD_SHA)
    monkeypatch.setattr(github_api, "get_nixbot_urls_from_github", lambda *a, **k: [NIXBOT_WEB_URL])
    monkeypatch.setattr(NixbotClient, "_get", fake_nixbot_get)


def test_cmd_pr_json_full_table(stub_nixbot: None, capsys: pytest.CaptureFixture[str]) -> None:
    code = _run([PR_URL, "--json"])
    assert code == 1

    out = json.loads(capsys.readouterr().out)
    ev = out["eval_build"]
    assert ev["url"] == NIXBOT_WEB_URL
    assert ev["status"] == "FAILED"
    assert len(ev["attributes"]) == 2
    by_attr = {s["attr"]: s for s in ev["attributes"]}
    assert by_attr["x86_64-linux.nixos-taps"]["status"] == "FAILED"
    assert by_attr["x86_64-linux.treefmt"]["status"] == "SUCCEEDED"


def test_cmd_pr_failures_json(stub_nixbot: None, capsys: pytest.CaptureFixture[str]) -> None:
    code = _run([PR_URL, "--failures", "--json", "--log-tail", "80"])
    assert code == 1

    out = json.loads(capsys.readouterr().out)
    assert out["pr"] == "mulatta/dots#235"
    assert out["status"] == "FAILED"
    assert out["eval_build"] == NIXBOT_WEB_URL
    assert len(out["failures"]) == 1
    fail = out["failures"][0]
    assert fail["attr"] == "x86_64-linux.nixos-taps"
    assert fail["status"] == "FAILED"
    assert fail["error"] == "boom"


def test_cmd_pr_text_output_is_structured(
    stub_nixbot: None, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run([PR_URL])
    assert code == 1
    out = capsys.readouterr().out
    assert "\x1b[" not in out  # no ANSI noise for the agent
    assert "status: FAILED" in out
    assert "x86_64-linux.nixos-taps" in out


def test_discovery_accepts_buildbot_prefixed_nixbot_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        github_api,
        "_gh_get",
        lambda url: (
            {
                "check_runs": [
                    {
                        "name": "buildbot/nix-build",
                        "app": {"name": "GitHub Actions"},
                        "details_url": NIXBOT_WEB_URL,
                    }
                ]
            }
            if url.endswith("/check-runs")
            else {"statuses": []}
        ),
    )
    assert github_api.get_nixbot_urls_from_github("mulatta", "dots", HEAD_SHA) == [NIXBOT_WEB_URL]


def test_discovery_error_when_nothing_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(github_api, "get_pr_head_sha", lambda *a, **k: HEAD_SHA)
    monkeypatch.setattr(github_api, "get_nixbot_urls_from_github", lambda *a, **k: [])
    code = _run([PR_URL, "--json"])
    assert code == 1
    err = capsys.readouterr().err
    assert "No nixbot status found" in err
