@echo off
rem MemorySafe launcher for the Claude Code and Codex plugins and the Claude Desktop
rem extension on Windows. The sibling of scripts/start: both hosts name an extensionless
rem command and resolve this file by its extension.
rem
rem stdout is the MCP channel. Nothing here may write to it: every message goes to stderr
rem or the install log, and the process on the other end of every exec speaks JSON-RPC.
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PLUGIN_DIR=%%~fI"
for /f "usebackq tokens=1,2 delims==" %%A in ("%SCRIPT_DIR%runtime.env") do set "%%A=%%B"

rem Claude Desktop leaves the optional directory token unresolved when the field is
rem blank. It is not a path; fall through to the platform's standard data root.
if "%MEMORYSAFE_INSTALL_ROOT%"=="${user_config.memory_directory}" set "MEMORYSAFE_INSTALL_ROOT="
if "%MEMORYSAFE_INSTALL_ROOT%"=="" set "MEMORYSAFE_INSTALL_ROOT=%LOCALAPPDATA%\MemorySafe"
set "DATA_ROOT=%MEMORYSAFE_INSTALL_ROOT%"

if "%MEMORYSAFE_DB_PATH%"=="" set "MEMORYSAFE_DB_PATH=%DATA_ROOT%\data\memorysafe.sqlite3"
if "%MEMORYSAFE_STATE_DIR%"=="" set "MEMORYSAFE_STATE_DIR=%DATA_ROOT%\runtime-state"
rem Only the plugin's own code. An inherited PYTHONPATH would put the user's packages
rem ahead of the hash-pinned ones in the runtime, and the lock would no longer decide
rem what runs. An inherited VIRTUAL_ENV would do the same to uv.
set "PYTHONPATH=%PLUGIN_DIR%\src"
set "VIRTUAL_ENV="
rem tiktoken caches its encoding in the system temp folder by default, so it downloaded
rem again whenever that was cleared, while the install guide promises nothing leaves this
rem computer after the first start. In the data root, one copy lasts.
set "TIKTOKEN_CACHE_DIR=%DATA_ROOT%\cache\tiktoken"
rem The one Windows footgun the official Python MCP servers document: without this a
rem non-UTF-8 console codepage can stall the stdio handshake.
set "PYTHONIOENCODING=utf-8"

if not exist "%DATA_ROOT%\data" mkdir "%DATA_ROOT%\data" 2>nul
if not exist "%MEMORYSAFE_STATE_DIR%\logs" mkdir "%MEMORYSAFE_STATE_DIR%\logs" 2>nul

set "RUNTIME_DIR=%DATA_ROOT%\runtime\%RUNTIME_KEY%"
set "RUNTIME_PYTHON=%RUNTIME_DIR%\Scripts\python.exe"
set "INSTALL_LOG=%MEMORYSAFE_STATE_DIR%\logs\claude-install.log"

call :write_cli_shim

if exist "%RUNTIME_PYTHON%" if exist "%RUNTIME_DIR%\ready" (
  "%RUNTIME_PYTHON%" "%SCRIPT_DIR%bootstrap_server.py"
  rem The percent form of this variable would be the value from before this block was
  rem entered - it is substituted when the block is parsed, not when this line runs.
  rem The bang form reads it live, after the command above has actually exited.
  exit /b !errorlevel!
)

rem First start: the proxy answers the handshake immediately and builds the runtime in
rem the background. Codex allows ten seconds and Claude Code thirty; the build takes longer.
set "MEMORYSAFE_RUNTIME_PENDING=1"
call :find_python
if not "!PROXY_PYTHON!"=="" (
  "!PROXY_PYTHON!" "%SCRIPT_DIR%bootstrap_server.py"
  exit /b !errorlevel!
)

rem No Python at all. uv provides one, downloading it before the handshake, so this one
rem start may miss Codex's window. The download finishes and the next start is instant.
set "UV="
for /f "usebackq delims=" %%U in (`call "%SCRIPT_DIR%ensure_uv.cmd" 2^>^>"%INSTALL_LOG%"`) do set "UV=%%U"
if not "!UV!"=="" (
  set "UV_PYTHON_INSTALL_DIR=%DATA_ROOT%\python"
  set "UV_CACHE_DIR=%DATA_ROOT%\cache\uv"
  rem uv rejects --managed-python and --python-preference together, so this is scoped to the
  rem install call and cleared before find runs, which relies on --managed-python alone. A
  rem `set` here is not scoped to one command the way POSIX start's inline VAR=value is, so a
  rem variable left standing would still be set when find runs next and uv would error out,
  rem leaving MANAGED_PYTHON empty on every Python-less machine.
  set "UV_PYTHON_PREFERENCE=only-managed"
  "!UV!" python install --no-bin %PYTHON_VERSION% >>"%INSTALL_LOG%" 2>&1
  set "UV_PYTHON_PREFERENCE="
  set "MANAGED_PYTHON="
  rem The backtick command must not start with a quoted token: with usebackq it runs
  rem through cmd /c, which strips the outer quotes of a command line that begins with
  rem a literal double quote and mis-parses the rest -- the same trap documented at
  rem length in ensure_uv.cmd (four failed attempts to read a checksum, there). `call`
  rem is a bare word, so it leads instead of "!UV!" (which resolves under
  rem %LOCALAPPDATA%, itself containing a space whenever the username does). Compare
  rem the safe capture two lines up, which already leads with `call` for this reason.
  for /f "usebackq delims=" %%P in (`call "!UV!" python find --managed-python %PYTHON_VERSION% 2^>^>"%INSTALL_LOG%"`) do set "MANAGED_PYTHON=%%P"
  if not "!MANAGED_PYTHON!"=="" (
    "!MANAGED_PYTHON!" "%SCRIPT_DIR%bootstrap_server.py"
    exit /b !errorlevel!
  )
)

rem Never exit without a server. Exiting shows as "Server disconnected" and takes every
rem MemorySafe tool with it, including the one that could explain the failure.
set "MEMORYSAFE_DEGRADED_REASON=no_python"
call :find_any_python
if not "!ANY_PYTHON!"=="" (
  "!ANY_PYTHON!" "%SCRIPT_DIR%degraded_server.py"
  exit /b !errorlevel!
)
echo MemorySafe: no usable Python was found and uv could not provide one. See %INSTALL_LOG%>&2
exit /b 1

:write_cli_shim
rem The memorysafe command follows whichever plugin started last, so it always runs that
rem plugin's code on the runtime built for its lock. It never edits a shell profile.
if not exist "%DATA_ROOT%\bin" mkdir "%DATA_ROOT%\bin" 2>nul
set "SHIM=%DATA_ROOT%\bin\memorysafe.cmd"
set "SHIM_TMP=%SHIM%.tmp"
(
  echo @echo off
  echo rem Written by the MemorySafe launcher on every start. Edits are overwritten.
  echo set "MEMORYSAFE_INSTALL_ROOT=%DATA_ROOT%"
  echo set "PYTHONPATH=%PLUGIN_DIR%\src"
  echo set "TIKTOKEN_CACHE_DIR=%DATA_ROOT%\cache\tiktoken"
  echo if not exist "%RUNTIME_PYTHON%" ^(
  echo   echo MemorySafe is still finishing its one-time setup. Try again in a minute.^>^&2
  echo   exit /b 1
  echo ^)
  echo "%RUNTIME_PYTHON%" -m memorysafe_chatgpt.cli %%*
) > "%SHIM_TMP%" 2>nul
move /y "%SHIM_TMP%" "%SHIM%" 1>nul 2>nul
exit /b 0

:find_python
set "PROXY_PYTHON="
if not "%PYTHON_SOURCE%"=="" (
  call :check_python "%PYTHON_SOURCE%" && set "PROXY_PYTHON=%PYTHON_SOURCE%"
  exit /b 0
)
for %%C in (python.exe python3.exe) do (
  for /f "usebackq delims=" %%P in (`where %%C 2^>nul`) do (
    if "!PROXY_PYTHON!"=="" (
      call :check_python "%%P" && set "PROXY_PYTHON=%%P"
    )
  )
)
exit /b 0

:find_any_python
set "ANY_PYTHON="
for %%C in (python.exe python3.exe py.exe) do (
  for /f "usebackq delims=" %%P in (`where %%C 2^>nul`) do (
    if "!ANY_PYTHON!"=="" set "ANY_PYTHON=%%P"
  )
)
exit /b 0

:check_python
rem The proxy is stdlib-only and parses as 3.8, so that is the floor. uv supplies the
rem real interpreter for the runtime.
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 8) else 1)" 1>nul 2>nul
exit /b !errorlevel!
