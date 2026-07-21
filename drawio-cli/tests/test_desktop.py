from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from drawio_cli.desktop import _has_gui_session, handoff_to_desktop


def test_handoff_launches_drawio_command_without_macos_open(tmp_path: Path) -> None:
    source = tmp_path / "diagram.drawio"
    source.write_text("<mxfile />")

    with (
        patch("drawio_cli.desktop._has_gui_session", return_value=True),
        patch("drawio_cli.desktop.subprocess.Popen") as popen,
    ):
        handoff_to_desktop(source, drawio="drawio")

    popen.assert_called_once_with(
        ["drawio", str(source)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def test_handoff_uses_drawio_env_override(tmp_path: Path) -> None:
    source = tmp_path / "diagram.drawio"
    source.write_text("<mxfile />")

    with (
        patch.dict("drawio_cli.desktop.os.environ", {"DRAWIO_CLI_DRAWIO": "custom"}),
        patch("drawio_cli.desktop._has_gui_session", return_value=True),
        patch("drawio_cli.desktop.subprocess.Popen") as popen,
    ):
        handoff_to_desktop(source)

    assert popen.call_args.args[0] == ["custom", str(source)]


def test_handoff_reports_launch_errors(tmp_path: Path) -> None:
    source = tmp_path / "diagram.drawio"
    source.write_text("<mxfile />")

    popen = Mock(side_effect=OSError("missing"))
    with (
        patch("drawio_cli.desktop._has_gui_session", return_value=True),
        patch("drawio_cli.desktop.subprocess.Popen", popen),
        pytest.raises(RuntimeError, match="failed to launch"),
    ):
        handoff_to_desktop(source)


def test_handoff_rejects_headless_sessions(tmp_path: Path) -> None:
    source = tmp_path / "diagram.drawio"
    source.write_text("<mxfile />")

    with (
        patch("drawio_cli.desktop._has_gui_session", return_value=False),
        pytest.raises(RuntimeError, match="GUI session"),
    ):
        handoff_to_desktop(source)


def test_gui_detection_uses_macos_session_environment() -> None:
    with (
        patch("drawio_cli.desktop.platform.system", return_value="Darwin"),
        patch.dict(
            "drawio_cli.desktop.os.environ", {"SECURITYSESSIONID": "186a2"}, clear=True
        ),
    ):
        assert _has_gui_session() is True


def test_gui_detection_rejects_headless_unix_environment() -> None:
    with (
        patch("drawio_cli.desktop.platform.system", return_value="Linux"),
        patch.dict("drawio_cli.desktop.os.environ", {}, clear=True),
    ):
        assert _has_gui_session() is False
