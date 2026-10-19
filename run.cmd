@echo off
REM VIGIL one-click launcher. Double-click this file (or run it from anywhere).
REM
REM This is a THIN shim, deliberately dumb -- same argument as vigil-serve.cmd:
REM   * cmd.exe parses this file byte-by-byte in the OEM codepage, so it stays
REM     ASCII-only. Every human-readable Chinese message comes from Python
REM     (scripts\run_vigil.py) instead.
REM   * The friendly checks (is .env filled? is there data? is the frontend
REM     built?) live in Python where they can be reasoned about and tested.
REM   * Its ONLY unique job is the case Python cannot handle: uv itself missing.
REM     If uv is not installed, `uv run ...` cannot start and would leave no
REM     trace -- this file is the only place that can say so plainly.
REM
REM Exit codes (from scripts\run_vigil.py): 0 ok, 3 config/.env needs the user,
REM 4 no data yet (run the pipeline first), 1 unexpected.
setlocal

REM run.cmd sits at the repo root, so %~dp0 IS the repo root (with a trailing
REM backslash). cd there so a double-click from any directory lands correctly.
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo.
  echo [VIGIL] Need "uv" but it was not found on PATH.
  echo.
  echo   uv is a single-file Python runner. Install it with one command:
  echo     powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
  echo   Then close this window and double-click run.cmd again.
  echo.
  pause
  exit /b 1
)

REM Make the environment match uv.lock (creates .venv on first run). This is
REM the "install dependencies" step a newcomer expects to see happening.
echo [VIGIL] Syncing Python dependencies ^(first run downloads; later runs are fast^)...
uv sync
if errorlevel 1 (
  echo.
  echo [VIGIL] Dependency sync failed. See the output above.
  echo.
  pause
  exit /b 1
)

REM Hand off to the Python launcher: checks .env / data / port / frontend, starts
REM the server, opens the browser. %* forwards any args (e.g. `run.cmd --port 8899`).
REM Ctrl-C stops it.
uv run python scripts\run_vigil.py %*
set "RC=%ERRORLEVEL%"

REM Keep the window open on a failure so a double-click user can read why.
if not "%RC%"=="0" pause
exit /b %RC%
