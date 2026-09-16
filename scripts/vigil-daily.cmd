@echo off
REM VIGIL daily pipeline. Invoked by Windows Task Scheduler.
REM
REM Why a .cmd wrapper instead of calling `vigil daily` directly:
REM Task Scheduler discards a task's stdout/stderr. If Python never starts
REM (uv missing from PATH, venv broken, dependency gone), a direct call
REM leaves NO trace at all -- the task just "did nothing". This wrapper is
REM the only place that can notice that case.
REM
REM ASCII-only on purpose: cmd.exe parses this file byte-by-byte in the OEM
REM codepage. All human-readable Chinese output comes from Python instead.
setlocal

REM Derive the repo root from THIS script's location (%~dp0 is the directory
REM holding this .cmd, with a trailing backslash). Hardcoding an absolute path
REM here would make -RepoPath a lie: the task would point at the new location
REM while this file still cd'd to the old one.
for %%I in ("%~dp0..") do set "REPO=%%~fI"
set "LOGDIR=%REPO%\data\logs"
set "ERRFILE=%LOGDIR%\LAST-ERROR.txt"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

REM Delete last run's error marker BEFORE starting: "file exists" then means
REM "THIS run failed". It also makes the fallback below meaningful -- when
REM Python wrote a detailed error we must not overwrite it with a generic one.
if exist "%ERRFILE%" del /q "%ERRFILE%"

cd /d "%REPO%"
uv run vigil daily
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" if not exist "%ERRFILE%" (
  > "%ERRFILE%" echo [%DATE% %TIME%] vigil daily exited with %RC% but wrote no LAST-ERROR.txt. This usually means Python failed before it started: uv not on PATH, broken venv, or a missing dependency. Run "uv run vigil daily" by hand in %REPO% to see the full error.
)

exit /b %RC%
