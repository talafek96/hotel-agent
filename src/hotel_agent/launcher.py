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

HOST = "0.0.0.0"
PORT = 8470
URL = f"http://localhost:{PORT}"
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


def is_server_running(host: str = "127.0.0.1", port: int = PORT) -> bool:
    """Check if the server is already listening on the given port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def _wait_for_server(
    host: str = "127.0.0.1", port: int = PORT, timeout: float = _STARTUP_TIMEOUT
) -> bool:
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
        "--no-dev",
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
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True  # new process group for killpg

    return subprocess.Popen(cmd, **kwargs)


ISSUES_URL = "https://github.com/talafek96/hotel-agent/issues"


def _ensure_deps(base_dir: Path, uv: Path) -> None:
    """Run ``uv sync --no-dev`` if .venv does not exist (first-run bootstrap)."""
    venv_dir = base_dir / ".venv"
    if venv_dir.exists():
        return

    log_path = _data_dir(base_dir) / "setup.log"

    print("=" * 50)
    print("  First-time setup — installing dependencies...")
    print("  This may take a minute. Please wait.")
    print("=" * 50)
    print()

    cmd = [str(uv), "sync", "--no-dev"]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(base_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        lines_seen = 0
        with open(log_path, "w", encoding="utf-8") as log_file:
            for line in proc.stdout:
                log_file.write(line)
                line = line.rstrip()
                if not line:
                    continue
                lines_seen += 1
                # Show a compact progress indicator, not the full output
                lower = line.lower()
                if any(
                    kw in lower
                    for kw in (
                        "downloading",
                        "creating",
                        "resolved",
                        "installed",
                        "building",
                        "built",
                        "using",
                    )
                ):
                    print(f"  {line}")
                elif lines_seen % 10 == 0:
                    print(f"  ... ({lines_seen} operations)")
        proc.wait(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("\nError: dependency installation timed out after 5 minutes.")
        print(f"  Log file: {log_path}")
        print("  Check your internet connection and try again.")
        _print_issue_hint(log_path)
        sys.exit(1)
    except FileNotFoundError:
        print(f"\nError: uv not found at {uv}")
        print("  Make sure the tools/ directory contains the uv binary.")
        _print_issue_hint(log_path)
        sys.exit(1)

    if proc.returncode != 0:
        print(f"\nError: dependency installation failed (exit code {proc.returncode}).")
        print(f"  Log file: {log_path}")
        # Show last few lines of the log on screen
        if log_path.exists():
            tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]
            print()
            for ln in tail:
                print(f"  {ln}")
        _print_issue_hint(log_path)
        sys.exit(1)

    print()
    print("  Setup complete!")
    print()


def _print_issue_hint(log_path: Path) -> None:
    """Print a hint to open a GitHub issue."""
    print()
    print("  If this error persists, please open an issue:")
    print(f"    {ISSUES_URL}/new")
    print(f"  Attach the log file: {log_path}")
    print("  Include a description of what went wrong and the error message.")


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


def _kill_process_tree(proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
    """Kill a process and all its children (works on Windows, Linux, macOS)."""
    pid = proc.pid
    try:
        if sys.platform == "win32":
            # taskkill /T kills the process tree on Windows
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            # On Unix, kill the process group
            import signal as _sig

            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(pid), _sig.SIGTERM)
    except Exception:
        pass
    # Final fallback: kill the process directly
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


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
    # Prefer ICO on Windows (has pre-rendered sizes with sharpening for small
    # tray icons); fall back to PNG, then to a solid-colour placeholder.
    ico_path = base_dir / "assets" / "icon.ico"
    png_path = base_dir / "assets" / "icon.png"
    if sys.platform == "win32" and ico_path.exists():
        image = Image.open(ico_path)
    elif png_path.exists():
        image = Image.open(png_path)
    elif ico_path.exists():
        image = Image.open(ico_path)
    else:
        image = Image.new("RGB", (64, 64), color=(59, 130, 246))

    def open_dashboard(icon: pystray.Icon, item: pystray.MenuItem) -> None:  # type: ignore[name-defined]
        _open_browser(URL)

    def open_settings(icon: pystray.Icon, item: pystray.MenuItem) -> None:  # type: ignore[name-defined]
        _open_browser(f"{URL}/config")

    def quit_app(icon: pystray.Icon, item: pystray.MenuItem) -> None:  # type: ignore[name-defined]
        # Just stop the icon — this causes icon.run() to return in the main thread.
        # Do NOT call sys.exit() or os._exit() here — that leaves the main thread alive.
        icon.visible = False
        icon.stop()

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

    # icon.run() blocks until icon.stop() is called (from quit_app)
    icon.run()

    # After icon.run() returns, clean up the server and exit
    log.info("Tray icon closed — shutting down server...")
    _kill_process_tree(server_proc)
    log.info("Server stopped.")


# ── Linux: daemon mode ────────────────────────────────


def _run_linux_daemon(server_proc: subprocess.Popen, base_dir: Path) -> None:  # type: ignore[type-arg]
    """Linux: write PID and wait for signals."""
    pid_path = _pid_file(base_dir)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")

    def _handle_term(signum: int, frame: object) -> None:
        _kill_process_tree(server_proc)
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
        _kill_process_tree(server_proc)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_term)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _handle_term)

    try:
        server_proc.wait()
    except KeyboardInterrupt:
        _kill_process_tree(server_proc)


# ── Auto-start on boot ────────────────────────────────

_APP_NAME = "HotelPriceTracker"


def is_autostart_enabled() -> bool:
    """Check whether the launcher is registered to run on OS startup."""
    if sys.platform == "win32":
        try:
            import winreg  # type: ignore[import-not-found]

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, _APP_NAME)
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except OSError:
            return False
    elif sys.platform == "darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"com.{_APP_NAME.lower()}.plist"
        return plist_path.exists()
    else:
        desktop_path = Path.home() / ".config" / "autostart" / f"{_APP_NAME}.desktop"
        return desktop_path.exists()


def _autostart_command(base_dir: Path) -> str:
    """Build the command string for OS startup registration.

    Frozen exe: just the exe path.
    Dev/uv mode: find uv on PATH + --directory + run command.
    """
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())
    import shutil

    uv = shutil.which("uv")
    if not uv:
        raise FileNotFoundError(
            "uv not found on PATH. Install it: "
            "https://docs.astral.sh/uv/getting-started/installation/"
        )
    project = str(base_dir.resolve())
    return f'"{uv}" run --no-dev --directory "{project}" hotel-agent-gui'


def set_autostart(base_dir: Path | None = None, *, enable: bool) -> None:
    """Register or unregister the launcher to run on OS startup."""
    if base_dir is None:
        base_dir = _resolve_base_dir()

    if sys.platform == "win32":
        import winreg  # type: ignore[import-not-found]

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if enable:
                cmd = _autostart_command(base_dir)
                winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, cmd)
                log.info("Autostart enabled: %s will start on login.", _APP_NAME)
            else:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, _APP_NAME)
                log.info("Autostart disabled: %s removed from startup.", _APP_NAME)
            winreg.CloseKey(key)
        except OSError as e:
            raise RuntimeError(f"Failed to modify startup registry: {e}") from e

    elif sys.platform == "darwin":
        plist_dir = Path.home() / "Library" / "LaunchAgents"
        plist_path = plist_dir / f"com.{_APP_NAME.lower()}.plist"
        if enable:
            plist_dir.mkdir(parents=True, exist_ok=True)
            cmd = _autostart_command(base_dir)
            plist_path.write_text(
                f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.{_APP_NAME.lower()}</string>
<key>ProgramArguments</key><array><string>{cmd}</string></array>
<key>RunAtLoad</key><true/>
</dict></plist>
""",
                encoding="utf-8",
            )
            log.info("Autostart enabled: %s", plist_path)
        else:
            plist_path.unlink(missing_ok=True)
            log.info("Autostart disabled: removed %s", plist_path)

    else:
        # Linux: ~/.config/autostart desktop entry
        autostart_dir = Path.home() / ".config" / "autostart"
        desktop_path = autostart_dir / f"{_APP_NAME}.desktop"
        if enable:
            autostart_dir.mkdir(parents=True, exist_ok=True)
            cmd = _autostart_command(base_dir)
            desktop_path.write_text(
                f"""[Desktop Entry]
Type=Application
Name={_APP_NAME}
Exec={cmd}
Hidden=false
X-GNOME-Autostart-enabled=true
""",
                encoding="utf-8",
            )
            log.info("Autostart enabled: %s", desktop_path)
        else:
            desktop_path.unlink(missing_ok=True)
            log.info("Autostart disabled: removed %s", desktop_path)


# ── Entry point ──────────────────────────────────────


def main() -> None:
    """Main entry point for the GUI launcher."""
    base_dir = _resolve_base_dir()
    log_dir = _data_dir(base_dir)

    # Log to both console and file (file is critical for --windowed .exe)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        file_handler = logging.FileHandler(log_dir / "launcher.log", encoding="utf-8")
        handlers.append(file_handler)
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    log.info("Launcher starting — base_dir=%s", base_dir)

    # Handle --stop flag
    if "--stop" in sys.argv:
        _stop_linux_daemon(base_dir)
        return

    # Handle --autostart / --no-autostart
    if "--autostart" in sys.argv:
        set_autostart(base_dir, enable=True)
        return
    if "--no-autostart" in sys.argv:
        set_autostart(base_dir, enable=False)
        return

    # If server is already running, just open the browser
    if is_server_running():
        log.info("Server already running at %s — opening browser.", URL)
        log.info("To stop the server, run this again with --stop")
        _open_browser(URL)
        return

    # Resolve uv and ensure deps are installed
    uv = _resolve_uv_path(base_dir)
    log.info("uv found at %s", uv)
    _ensure_config(base_dir)
    _ensure_deps(base_dir, uv)

    # Start the server
    log.info("Starting server subprocess...")
    server_proc = _start_server(base_dir, uv)
    log.info("Server subprocess started (PID %s), waiting for ready...", server_proc.pid)

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
        _kill_process_tree(server_proc)
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
