"""Tests for the GUI launcher module."""

from __future__ import annotations

import signal
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hotel_agent.launcher import (
    _ensure_deps,
    _pid_file,
    _resolve_base_dir,
    _resolve_uv_path,
    _stop_linux_daemon,
    _wait_for_server,
    is_server_running,
)


class TestIsServerRunning:
    """Tests for port-check logic."""

    def test_returns_false_when_nothing_listening(self):
        # Use a port that's almost certainly not in use
        assert is_server_running("127.0.0.1", 19876) is False

    def test_returns_true_when_port_open(self):
        """Bind a socket and verify is_server_running detects it."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            assert is_server_running("127.0.0.1", port) is True
        finally:
            sock.close()


class TestWaitForServer:
    """Tests for server readiness polling."""

    def test_returns_true_immediately_if_running(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            assert _wait_for_server("127.0.0.1", port, timeout=2) is True
        finally:
            sock.close()

    def test_returns_false_on_timeout(self):
        assert _wait_for_server("127.0.0.1", 19877, timeout=0.5) is False


class TestResolveBaseDir:
    """Tests for project root resolution."""

    def test_returns_project_root(self):
        base = _resolve_base_dir()
        assert (base / "pyproject.toml").exists()
        assert (base / "src" / "hotel_agent").is_dir()

    def test_frozen_mode_uses_executable(self):
        with patch("hotel_agent.launcher.sys") as mock_sys:
            mock_sys.frozen = True
            mock_sys.executable = "/opt/app/HotelPriceTracker"
            mock_sys.platform = "linux"
            result = _resolve_base_dir()
            assert result == Path("/opt/app")


class TestResolveUvPath:
    """Tests for uv binary resolution."""

    def test_finds_bundled_uv(self, tmp_path):
        tools = tmp_path / "tools"
        tools.mkdir()
        uv_bin = tools / "uv"
        uv_bin.write_text("#!/bin/sh\n")
        result = _resolve_uv_path(tmp_path)
        assert result == uv_bin

    def test_finds_bundled_uv_exe(self, tmp_path):
        tools = tmp_path / "tools"
        tools.mkdir()
        uv_bin = tools / "uv.exe"
        uv_bin.write_text("")
        with patch("hotel_agent.launcher.sys") as mock_sys:
            mock_sys.platform = "win32"
            result = _resolve_uv_path(tmp_path)
        assert result == uv_bin

    def test_falls_back_to_path(self, tmp_path):
        with patch("shutil.which", return_value="/usr/local/bin/uv"):
            result = _resolve_uv_path(tmp_path)
        assert result == Path("/usr/local/bin/uv")

    def test_raises_if_not_found(self, tmp_path):
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(FileNotFoundError, match="uv binary not found"),
        ):
            _resolve_uv_path(tmp_path)


class TestEnsureDeps:
    """Tests for first-run dependency installation."""

    def test_skips_if_venv_exists(self, tmp_path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        uv = tmp_path / "uv"
        # Should not call subprocess at all
        with patch("hotel_agent.launcher.subprocess.run") as mock_run:
            _ensure_deps(tmp_path, uv)
            mock_run.assert_not_called()

    def test_runs_uv_sync_on_first_run(self, tmp_path):
        uv = tmp_path / "uv"
        with patch("hotel_agent.launcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _ensure_deps(tmp_path, uv)
            mock_run.assert_called_once()
            args = mock_run.call_args
            assert str(uv) in args[0][0][0]
            assert "sync" in args[0][0]

    def test_raises_on_uv_sync_failure(self, tmp_path):
        uv = tmp_path / "uv"
        with patch("hotel_agent.launcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error msg")
            with pytest.raises(RuntimeError, match="uv sync failed"):
                _ensure_deps(tmp_path, uv)


class TestPidFile:
    """Tests for PID file management."""

    def test_pid_file_path(self, tmp_path):
        result = _pid_file(tmp_path)
        assert result == tmp_path / "data" / "hotel-agent.pid"
        assert result.parent.exists()


class TestStopLinuxDaemon:
    """Tests for the --stop flag logic."""

    def test_stop_sends_sigterm(self, tmp_path):
        pid_path = tmp_path / "data" / "hotel-agent.pid"
        pid_path.parent.mkdir(parents=True)
        pid_path.write_text("12345")

        with patch("os.kill") as mock_kill:
            _stop_linux_daemon(tmp_path)
            mock_kill.assert_called_once_with(12345, signal.SIGTERM)

    def test_stop_cleans_stale_pid(self, tmp_path):
        pid_path = tmp_path / "data" / "hotel-agent.pid"
        pid_path.parent.mkdir(parents=True)
        pid_path.write_text("99999")

        with patch("os.kill", side_effect=ProcessLookupError):
            _stop_linux_daemon(tmp_path)
        assert not pid_path.exists()

    def test_stop_exits_if_no_pid_file(self, tmp_path):
        with pytest.raises(SystemExit):
            _stop_linux_daemon(tmp_path)
