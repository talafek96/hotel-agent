"""GUI launcher for Hotel Price Tracker.

Starts the web server in the background and provides platform-specific
management: system tray icon on Windows/macOS, PID-based daemon on Linux.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8470
URL = f"http://{HOST}:{PORT}"
_POLL_INTERVAL = 0.5
_STARTUP_TIMEOUT = 120  # seconds to wait for server ready


def _open_browser(url: str) -> None:
    """Open URL in the default browser, handling WSL and headless environments."""
    # WSL: try Windows browser via cmd.exe
    if sys.platform != "win32" and "microsoft" in (os.uname().release or "").lower():
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", "start", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except FileNotFoundError:
            pass

    try:
        webbrowser.open(url)
    except Exception:
        log.info("Open this URL in your browser: %s", url)


def _resolve_base_dir() -> Path:
    """Resolve the project root directory.

    When running as a PyInstaller frozen binary, the exe sits next to the
    distribution files (src/, tools/, etc.).  When running as a normal
    Python script, we walk up from this file to find the project root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def _resolve_uv_path(base_dir: Path) -> Path:
    """Find the uv binary — bundled in tools/ or on PATH."""
    if sys.platform == "win32":
        bundled = base_dir / "tools" / "uv.exe"
    else:
        bundled = base_dir / "tools" / "uv"

    if bundled.exists():
        return bundled

    # Fall back to uv on PATH
    import shutil

    on_path = shutil.which("uv")
    if on_path:
        return Path(on_path)

    raise FileNotFoundError(
        "uv binary not found. Place it in tools/ or install it: "
        "https://docs.astral.sh/uv/getting-started/installation/"
    )


def is_server_running(host: str = HOST, port: int = PORT) -> bool:
    """Check if the server is already listening on the given port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def _wait_for_server(host: str = HOST, port: int = PORT, timeout: float = _STARTUP_TIMEOUT) -> bool:
    """Block until the server is accepting connections or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_server_running(host, port):
            return True
        time.sleep(_POLL_INTERVAL)
    return False


def _start_server(base_dir: Path, uv: Path) -> subprocess.Popen:  # type: ignore[type-arg]
    """Start the hotel-agent web server as a subprocess."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [
        str(uv),
        "run",
        "hotel-agent",
        "serve",
        "--port",
        str(PORT),
        "--host",
        HOST,
    ]

    kwargs: dict = {
        "cwd": str(base_dir),
        "env": env,
        "stdout": open(  # noqa: SIM115
            _data_dir(base_dir) / "server.log", "w", encoding="utf-8"
        ),
        "stderr": subprocess.STDOUT,
    }

    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    return subprocess.Popen(cmd, **kwargs)


def _ensure_deps(base_dir: Path, uv: Path) -> None:
    """Run ``uv sync --no-dev`` if .venv does not exist (first-run bootstrap)."""
    venv_dir = base_dir / ".venv"
    if venv_dir.exists():
        return

    log.info("First run — installing dependencies (this may take a minute)...")
    cmd = [str(uv), "sync", "--no-dev"]
    result = subprocess.run(
        cmd,
        cwd=str(base_dir),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"uv sync failed:\n{result.stderr}")
    log.info("Dependencies installed.")


def _ensure_config(base_dir: Path) -> None:
    """Copy config.example.yaml to config.yaml if it doesn't exist."""
    config_path = base_dir / "config.yaml"
    example_path = base_dir / "config.example.yaml"
    if not config_path.exists() and example_path.exists():
        import shutil

        shutil.copy2(example_path, config_path)
        log.info("Created config.yaml from config.example.yaml")


def _data_dir(base_dir: Path) -> Path:
    """Ensure data/ directory exists and return it."""
    d = base_dir / "data"
    d.mkdir(exist_ok=True)
    return d


def _pid_file(base_dir: Path) -> Path:
    return _data_dir(base_dir) / "hotel-agent.pid"


# ── Windows / macOS: system tray ──────────────────────


def _run_tray(server_proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
    """Run a system tray icon (Windows/macOS)."""
    try:
        import pystray
        from PIL import Image
    except ImportError as exc:
        log.warning("pystray/Pillow not installed (%s) — running headless.", exc)
        _run_headless(server_proc)
        return

    base_dir = _resolve_base_dir()
    icon_path = base_dir / "assets" / "icon.png"
    if not icon_path.exists():
        icon_path = base_dir / "assets" / "icon.ico"
    if not icon_path.exists():
        # Create a minimal fallback icon
        image = Image.new("RGB", (64, 64), color=(59, 130, 246))
    else:
        image = Image.open(icon_path)

    def open_dashboard(icon: pystray.Icon, item: pystray.MenuItem) -> None:  # type: ignore[name-defined]
        _open_browser(URL)

    def open_settings(icon: pystray.Icon, item: pystray.MenuItem) -> None:  # type: ignore[name-defined]
        _open_browser(f"{URL}/config")

    def quit_app(icon: pystray.Icon, item: pystray.MenuItem) -> None:  # type: ignore[name-defined]
        icon.stop()
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()

    icon = pystray.Icon(
        "hotel-price-tracker",
        image,
        "Hotel Price Tracker",
        menu=pystray.Menu(
            pystray.MenuItem("Open Dashboard", open_dashboard, default=True),
            pystray.MenuItem("Settings", open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", quit_app),
        ),
    )

    # Show balloon notification on first run
    def _notify_first_run() -> None:
        time.sleep(1)
        with contextlib.suppress(Exception):
            icon.notify(
                "Hotel Price Tracker is running.\nOpen your browser or double-click this icon."
            )

    threading.Thread(target=_notify_first_run, daemon=True).start()

    icon.run()


# ── Linux: daemon mode ────────────────────────────────


def _run_linux_daemon(server_proc: subprocess.Popen, base_dir: Path) -> None:  # type: ignore[type-arg]
    """Linux: write PID and wait for signals."""
    pid_path = _pid_file(base_dir)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")

    def _handle_term(signum: int, frame: object) -> None:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        pid_path.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_term)
    signal.signal(signal.SIGINT, _handle_term)

    print(f"Hotel Price Tracker running at {URL}")
    print(f"PID file: {pid_path}")
    print(f"Stop with: {sys.argv[0]} --stop")

    try:
        server_proc.wait()
    finally:
        pid_path.unlink(missing_ok=True)


def _stop_linux_daemon(base_dir: Path) -> None:
    """Stop the server by finding and killing the process on PORT."""
    pid_path = _pid_file(base_dir)

    if not is_server_running():
        print(f"No server running on port {PORT}.")
        pid_path.unlink(missing_ok=True)
        return

    # Try PID file first (most reliable if launcher started the server)
    if pid_path.exists():
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Server stopped (PID {pid}).")
            pid_path.unlink(missing_ok=True)
            return
        except ProcessLookupError:
            pid_path.unlink(missing_ok=True)
        except PermissionError:
            print(f"Permission denied for PID {pid}.")
            sys.exit(1)

    # Fall back to finding the process by port
    found_pid = _find_pid_on_port(PORT)
    if found_pid:
        try:
            os.kill(found_pid, signal.SIGTERM)
            print(f"Server stopped (PID {found_pid} on port {PORT}).")
        except ProcessLookupError:
            print("Process already exited.")
        except PermissionError:
            print(f"Permission denied for PID {found_pid}. Try: sudo kill {found_pid}")
            sys.exit(1)
    else:
        print(f"Could not find process on port {PORT}. Try: lsof -ti :{PORT} | xargs kill")


def _find_pid_on_port(port: int) -> int | None:
    """Find the PID of the process listening on the given port."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    return int(parts[-1])
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip().splitlines()[0])
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


# ── Headless fallback ─────────────────────────────────


def _run_headless(server_proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
    """Headless mode: just wait for the server process."""
    print(f"Hotel Price Tracker running at {URL}")
    print("Press Ctrl+C to stop.")

    def _handle_term(signum: int, frame: object) -> None:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_term)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _handle_term)

    try:
        server_proc.wait()
    except KeyboardInterrupt:
        server_proc.terminate()


# ── Entry point ──────────────────────────────────────


def main() -> None:
    """Main entry point for the GUI launcher."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    base_dir = _resolve_base_dir()

    # Handle --stop flag (Linux)
    if "--stop" in sys.argv:
        _stop_linux_daemon(base_dir)
        return

    # If server is already running, just open the browser
    if is_server_running():
        log.info("Server already running at %s — opening browser.", URL)
        log.info("To stop the server, run this again with --stop")
        _open_browser(URL)
        return

    # Resolve uv and ensure deps are installed
    uv = _resolve_uv_path(base_dir)
    _ensure_config(base_dir)
    _ensure_deps(base_dir, uv)

    # Start the server
    log.info("Starting server...")
    server_proc = _start_server(base_dir, uv)

    # Wait for server to be ready
    if not _wait_for_server():
        # Server failed — check if it crashed
        server_log = _data_dir(base_dir) / "server.log"
        log.error("Server failed to start within %ds.", _STARTUP_TIMEOUT)
        if server_log.exists():
            log.error(
                "Server log (last 20 lines):\n%s",
                "\n".join(
                    server_log.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
                ),
            )
        server_proc.terminate()
        sys.exit(1)

    log.info("Server ready at %s", URL)
    _open_browser(URL)

    # Platform-specific run loop
    if sys.platform == "win32" or sys.platform == "darwin":
        _run_tray(server_proc)
    else:
        _run_linux_daemon(server_proc, base_dir)


if __name__ == "__main__":
    main()
