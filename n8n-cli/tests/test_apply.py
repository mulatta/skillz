"""Apply command tests."""

import json
from pathlib import Path

import pytest

from n8n_cli.commands.apply import _strip_for_create, _strip_for_update, _workflows_differ

from tests.conftest import WORKFLOW_1, run_fail, run_ok


class TestApplyCommand:
    def test_create_new(
        self,
        server: tuple[str, int],
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """apply creates workflow when local file has no ID."""
        wf = {"name": "Brand New", "nodes": [], "connections": {}}
        (tmp_path / "new.json").write_text(json.dumps(wf))
        out = run_ok(server, ["apply", "-d", str(tmp_path)], capsys)
        assert "create" in out.lower()
        # File should be updated with server-assigned ID
        data = json.loads((tmp_path / "new.json").read_text())
        assert data.get("id") is not None

    def test_dry_run(
        self,
        server: tuple[str, int],
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """apply --dry-run previews without changes."""
        wf = {"name": "Dry Run Test", "nodes": [], "connections": {}}
        (tmp_path / "dry.json").write_text(json.dumps(wf))
        out = run_ok(server, ["apply", "-d", str(tmp_path), "--dry-run"], capsys)
        assert "create" in out.lower()
        # File should NOT be updated
        data = json.loads((tmp_path / "dry.json").read_text())
        assert "id" not in data

    def test_skip_unchanged(
        self,
        server: tuple[str, int],
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """apply skips workflows that match remote."""
        (tmp_path / "existing.json").write_text(json.dumps(WORKFLOW_1))
        out = run_ok(server, ["apply", "-d", str(tmp_path)], capsys)
        assert "skip" in out.lower()

    def test_ignores_remote_binary_mode_setting(self) -> None:
        """apply does not treat server-injected settings.binaryMode as drift."""
        local = {
            **WORKFLOW_1,
            "settings": {"executionOrder": "v1"},
        }
        remote = {
            **WORKFLOW_1,
            "settings": {"executionOrder": "v1", "binaryMode": "separate"},
        }

        assert not _workflows_differ(local, remote)

    def test_strips_binary_mode_from_write_bodies(self) -> None:
        """n8n exposes settings.binaryMode but rejects it on create/update."""
        wf = {
            **WORKFLOW_1,
            "settings": {"executionOrder": "v1", "binaryMode": "separate"},
        }

        assert _strip_for_create(wf)["settings"] == {"executionOrder": "v1"}
        assert _strip_for_update(wf)["settings"] == {"executionOrder": "v1"}

    def test_ignores_server_normalized_node_layout_and_datatable_resource(self) -> None:
        """n8n normalizes cosmetic node fields after accepting workflow updates."""
        local = {
            **WORKFLOW_1,
            "nodes": [
                {
                    "name": "Get Rows",
                    "type": "n8n-nodes-base.dataTable",
                    "typeVersion": 1.1,
                    "position": [980, 220],
                    "parameters": {"resource": "row", "operation": "get"},
                }
            ],
        }
        remote = {
            **WORKFLOW_1,
            "nodes": [
                {
                    "name": "Get Rows",
                    "type": "n8n-nodes-base.dataTable",
                    "typeVersion": 1.1,
                    "position": [992, 224],
                    "parameters": {"operation": "get"},
                }
            ],
        }

        assert not _workflows_differ(local, remote)

    def test_detects_runtime_node_parameter_changes(self) -> None:
        """node parameter changes remain meaningful drift."""
        local = {
            **WORKFLOW_1,
            "nodes": [
                {
                    "name": "Code",
                    "type": "n8n-nodes-base.code",
                    "parameters": {"jsCode": "return [];"},
                }
            ],
        }
        remote = {
            **WORKFLOW_1,
            "nodes": [
                {
                    "name": "Code",
                    "type": "n8n-nodes-base.code",
                    "parameters": {"jsCode": "return [1];"},
                }
            ],
        }

        assert _workflows_differ(local, remote)

    def test_empty_dir(
        self,
        server: tuple[str, int],
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """apply with empty directory prints message."""
        out = run_ok(server, ["apply", "-d", str(tmp_path)], capsys)
        assert "No workflow files found" in out

    def test_missing_dir(
        self,
        server: tuple[str, int],
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """apply with nonexistent directory shows error."""
        err = run_fail(server, ["apply", "-d", str(tmp_path / "nope")], capsys)
        assert "not found" in err.lower() or "Directory" in err
