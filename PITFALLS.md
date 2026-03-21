# Pitfalls

## git describe fails under set -e in GitHub Actions
- **Symptom**: Release workflow "Compute version" step exits with code 128
- **Cause**: `git describe --tags` returns 128 when no tags are reachable; `set -e -o pipefail` (bash default in Actions) aborts the script before the fallback runs
- **Fix**: Append `|| true` so the non-zero exit doesn't abort, then check if the result is empty
- **Commit**: 28e17c6

## git describe output is ambiguous with dash-separated patch tags
- **Symptom**: `v2026.03.21-1-3-gabcdef` — can't tell if `-1` is a patch number or commit distance
- **Cause**: `git describe` uses `-` to separate tag, distance, and hash — same separator as our `vYYYY.MM.DD-N` patch convention
- **Fix**: For tag-triggered builds, extract version directly from `GITHUB_REF` (no parsing). Only use `git describe` for `workflow_dispatch` dev builds.
- **Commit**: df3ffa7

## config.example.yaml rates: None crashes pydantic
- **Symptom**: Server fails to start with `ValidationError: currency.rates — Input should be a valid dictionary, got NoneType`
- **Cause**: YAML `rates:` with only commented-out entries parses as `None`, not `{}`
- **Fix**: Add `@field_validator("rates", mode="before")` that coerces `None` to `{}`
- **Commit**: f2dc129

## os.uname() doesn't exist on Windows
- **Symptom**: `AttributeError: module 'os' has no attribute 'uname'` on Windows PyInstaller binary
- **Cause**: `os.uname()` is Unix-only; called unconditionally in WSL browser detection
- **Fix**: Guard with `sys.platform != "win32"` before calling `os.uname()`
- **Commit**: c6336bc

## Stale Windows process steals port from WSL launcher
- **Symptom**: Linux dist launcher opens browser to "Internal Server Error" despite server starting correctly
- **Cause**: A broken Windows .exe was still holding port 8470 invisibly (no tray icon). The WSL launcher's `is_server_running()` detected the port as occupied, skipped starting a new server, and opened the browser to the broken Windows process.
- **Fix**: Kill stale processes on the port before testing. On Windows: `netstat -ano | findstr :8470` then `taskkill /F /PID <pid>`. On Linux: `lsof -ti :8470 | xargs kill`.
- **Lesson**: When debugging "Internal Server Error", always check if another process owns the port first.
