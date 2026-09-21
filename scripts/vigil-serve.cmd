@echo off
REM VIGIL read-only web service (127.0.0.1:8787, proxied by `tailscale serve`).
REM Started by Windows Task Scheduler at logon -- see scripts\register-serve-task.ps1.
REM
REM This wrapper is deliberately dumb: it pins the environment invariants and
REM hands off to scripts\serve_supervisor.py, which owns the restart policy.
REM The supervision loop lived here in a first version and FAILED -- see the
REM supervisor's module docstring for the measured reasons (cmd's goto re-reads
REM the executing file; `>>` across processes fails silently to stderr, which
REM Task Scheduler discards). Logic lives in Python; this file stays ASCII.
REM
REM Why a .cmd wrapper at all instead of running the supervisor directly:
REM   1. Task Scheduler discards a task's stdout/stderr; this wrapper is the
REM      only place that can notice "Python never started" (uv off PATH, broken
REM      venv) and leave a trace -- same argument as vigil-daily.cmd.
REM   2. cmd.exe runs it without any PowerShell execution-policy dependency
REM      (see section 10 of the ops setup doc in docs/).
REM
REM ASCII-only on purpose: cmd.exe parses this file byte-by-byte in the OEM
REM codepage. All human-readable Chinese output comes from Python.
setlocal

REM Derive the repo root from THIS script's location (%~dp0 is the directory
REM holding this .cmd, with a trailing backslash) -- same rule as
REM vigil-daily.cmd, so -RepoPath in the register script stays the only
REM place a move has to be recorded that is not the repo itself.
for %%I in ("%~dp0..") do set "REPO=%%~fI"
set "LOGDIR=%REPO%\data\logs"
set "LOGFILE=%LOGDIR%\vigil-serve.log"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

cd /d "%REPO%"
uv run python scripts\serve_supervisor.py
set "RC=%ERRORLEVEL%"

REM Non-zero means supervision ended without the server running forever. The
REM supervisor writes its own narrative for crashes and give-ups; this line
REM is the wrapper's closing note, and it is also the ONLY trace for "Python
REM never started" (uv missing, broken venv) -- in that case no supervisor
REM lines appear above it. Appended unconditionally on failure: a stale log
REM must not be mistakable for a fresh one.
if not "%RC%"=="0" (
  >> "%LOGFILE%" echo [%DATE% %TIME%] vigil serve supervision exited with %RC%. If no fresh supervisor entry appears above for this run, Python never started: uv not on PATH, broken venv, or a missing dependency. Run "uv run python scripts\serve_supervisor.py" by hand in %REPO% to see the full error.
)

exit /b %RC%
