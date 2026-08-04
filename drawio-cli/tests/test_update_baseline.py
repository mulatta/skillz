# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).parents[1] / "index-builder" / "update-baseline.py"


def _manifest() -> dict[str, Any]:
    return {
        "complete": True,
        "drawioVersion": "1.0",
        "registrations": 3,
        "executedFactories": 3,
        "capturedItems": 4,
        "entriesAfterDedup": 3,
        "kindCounts": {"vertex": 3},
        "canaries": {"shape": True},
        "resources": {"requested": 1, "failed": 0, "remote": 0},
        "indexSha256": "0" * 64,
    }


def _baseline() -> dict[str, Any]:
    manifest = _manifest()
    return {
        "drawioVersion": manifest["drawioVersion"],
        "entryCount": manifest["entriesAfterDedup"],
        "indexSha256": manifest["indexSha256"],
        "registrations": manifest["registrations"],
        "capturedItems": manifest["capturedItems"],
        "kindCounts": manifest["kindCounts"],
    }


def _run(
    manifest: Path, expected: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(manifest),
            "--expected",
            str(expected),
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_updater_handles_version_bump(tmp_path: Path) -> None:
    candidate = _manifest()
    candidate["drawioVersion"] = "2.0"
    candidate["indexSha256"] = "1" * 64
    manifest = tmp_path / "manifest.json"
    expected = tmp_path / "expected.json"
    manifest.write_text(json.dumps(candidate))
    expected.write_text(json.dumps(_baseline(), indent=2) + "\n")
    expected.chmod(0o640)
    before = expected.read_bytes()

    check = _run(manifest, expected, "--check")
    assert check.returncode == 1
    assert expected.read_bytes() == before

    accepted = _run(manifest, expected)
    assert accepted.returncode == 0
    updated = json.loads(expected.read_bytes())
    assert updated["drawioVersion"] == "2.0"
    assert updated["indexSha256"] == "1" * 64
    assert updated["entryCount"] == _baseline()["entryCount"]
    assert updated["kindCounts"] == _baseline()["kindCounts"]
    assert stat.S_IMODE(expected.stat().st_mode) == 0o640


def test_updater_rejects_incomplete_candidate_without_writing(tmp_path: Path) -> None:
    data = _manifest()
    data["complete"] = False
    manifest = tmp_path / "manifest.json"
    expected = tmp_path / "expected.json"
    manifest.write_text(json.dumps(data))
    expected.write_text("keep me\n")

    result = _run(manifest, expected, "--accept")

    assert result.returncode == 2
    assert "candidate manifest is incomplete" in result.stderr
    assert expected.read_text() == "keep me\n"
