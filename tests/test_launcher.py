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
    is_autostart_enabled,
    is_server_running,
    set_autostart,
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
        with patch("hotel_agent.launcher.subprocess.Popen") as mock_popen:
            _ensure_deps(tmp_path, uv)
            mock_popen.assert_not_called()

    def test_runs_uv_sync_on_first_run(self, tmp_path):
        uv = tmp_path / "uv"
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["Downloading...\n", "Installed 10 packages\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        with patch("hotel_agent.launcher.subprocess.Popen", return_value=mock_proc) as mock_popen:
            _ensure_deps(tmp_path, uv)
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            assert str(uv) in cmd[0]
            assert "--no-dev" in cmd

    def test_exits_on_uv_sync_failure(self, tmp_path):
        uv = tmp_path / "uv"
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["error: failed\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1
        with (
            patch("hotel_agent.launcher.subprocess.Popen", return_value=mock_proc),
            pytest.raises(SystemExit),
        ):
            _ensure_deps(tmp_path, uv)


class TestPidFile:
    """Tests for PID file management."""

    def test_pid_file_path(self, tmp_path):
        result = _pid_file(tmp_path)
        assert result == tmp_path / "data" / "hotel-agent.pid"
        assert result.parent.exists()


class TestStopLinuxDaemon:
    """Tests for the --stop flag logic."""

    def test_stop_sends_sigterm_via_pid_file(self, tmp_path):
        pid_path = tmp_path / "data" / "hotel-agent.pid"
        pid_path.parent.mkdir(parents=True)
        pid_path.write_text("12345")

        with (
            patch("hotel_agent.launcher.is_server_running", return_value=True),
            patch("os.kill") as mock_kill,
        ):
            _stop_linux_daemon(tmp_path)
            mock_kill.assert_called_once_with(12345, signal.SIGTERM)

    def test_stop_cleans_stale_pid(self, tmp_path):
        pid_path = tmp_path / "data" / "hotel-agent.pid"
        pid_path.parent.mkdir(parents=True)
        pid_path.write_text("99999")

        with (
            patch("hotel_agent.launcher.is_server_running", return_value=True),
            patch("os.kill", side_effect=ProcessLookupError),
            patch("hotel_agent.launcher._find_pid_on_port", return_value=None),
        ):
            _stop_linux_daemon(tmp_path)
        assert not pid_path.exists()

    def test_stop_when_not_running(self, tmp_path, capsys):
        with patch("hotel_agent.launcher.is_server_running", return_value=False):
            _stop_linux_daemon(tmp_path)
        assert "No server running" in capsys.readouterr().out

    def test_stop_falls_back_to_port_lookup(self, tmp_path):
        """When no PID file exists, find process by port."""
        with (
            patch("hotel_agent.launcher.is_server_running", return_value=True),
            patch("hotel_agent.launcher._find_pid_on_port", return_value=54321) as mock_find,
            patch("os.kill") as mock_kill,
        ):
            _stop_linux_daemon(tmp_path)
            mock_find.assert_called_once()
            mock_kill.assert_called_once_with(54321, signal.SIGTERM)


class TestAutostart:
    """Tests for autostart enable/disable/detect on Linux."""

    def test_is_autostart_enabled_false_by_default(self, tmp_path):
        """No desktop file → autostart disabled."""
        with patch("hotel_agent.launcher.Path.home", return_value=tmp_path):
            assert is_autostart_enabled() is False

    def test_set_autostart_creates_desktop_file(self, tmp_path):
        """Enabling autostart creates the .desktop file."""
        with patch("hotel_agent.launcher.Path.home", return_value=tmp_path):
            set_autostart(tmp_path, enable=True)
        desktop = tmp_path / ".config" / "autostart" / "HotelPriceTracker.desktop"
        assert desktop.exists()
        content = desktop.read_text()
        assert "X-GNOME-Autostart-enabled=true" in content

    def test_set_autostart_then_detect(self, tmp_path):
        """Enable → detect → True; disable → detect → False."""
        with patch("hotel_agent.launcher.Path.home", return_value=tmp_path):
            set_autostart(tmp_path, enable=True)
            assert is_autostart_enabled() is True
            set_autostart(tmp_path, enable=False)
            assert is_autostart_enabled() is False

    def test_disable_when_not_set(self, tmp_path):
        """Disabling when not set should not raise."""
        with patch("hotel_agent.launcher.Path.home", return_value=tmp_path):
            set_autostart(tmp_path, enable=False)
            assert is_autostart_enabled() is False
