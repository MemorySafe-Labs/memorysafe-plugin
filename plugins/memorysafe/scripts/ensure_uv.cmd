@echo off
rem Print the path of a verified uv.exe, downloading the pinned release on first use.
rem
rem stdout carries only that path: install_runtime.py and start.cmd read it. Exit codes
rem match the POSIX ensure_uv: 2 download failed, 3 checksum mismatch, 4 data folder not
rem writable, 1 anything else.
rem
rem Every tool is named by its absolute System32 path. The MCP SDK does not pass PATHEXT
rem or COMSPEC to the child, and a bare "tar" can resolve to Git for Windows' GNU tar,
rem which cannot read a .zip at all.
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "CURL=%SystemRoot%\System32\curl.exe"
set "TAR=%SystemRoot%\System32\tar.exe"
set "CERTUTIL=%SystemRoot%\System32\certutil.exe"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "FINDSTR=%SystemRoot%\System32\findstr.exe"

for /f "usebackq tokens=1,2 delims==" %%A in ("%SCRIPT_DIR%runtime.env") do set "%%A=%%B"

if "%MEMORYSAFE_INSTALL_ROOT%"=="" (
  echo MEMORYSAFE_INSTALL_ROOT must be set.>&2
  exit /b 1
)
set "DATA_ROOT=%MEMORYSAFE_INSTALL_ROOT%"

if not "%MEMORYSAFE_UV%"=="" (
  rem A locked-down network can still run MemorySafe with a uv the user installed.
  if exist "%MEMORYSAFE_UV%" (
    echo %MEMORYSAFE_UV%
    exit /b 0
  )
  echo MEMORYSAFE_UV is set to %MEMORYSAFE_UV%, which is not an executable file.>&2
  exit /b 2
)

set "TARGET_DIR=%DATA_ROOT%\tools\uv-%UV_VERSION%"
if exist "%TARGET_DIR%\uv.exe" (
  echo %TARGET_DIR%\uv.exe
  exit /b 0
)

if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
  set "TARGET=aarch64-pc-windows-msvc"
) else (
  set "TARGET=x86_64-pc-windows-msvc"
)
set "ARCHIVE_NAME=uv-!TARGET!.zip"

set "EXPECTED="
for /f "usebackq tokens=1,2" %%A in ("%SCRIPT_DIR%uv-checksums") do (
  if /i "%%B"=="!ARCHIVE_NAME!" set "EXPECTED=%%A"
)
if "!EXPECTED!"=="" (
  echo No checksum is recorded for !ARCHIVE_NAME!, so it will not be downloaded.>&2
  exit /b 3
)

if not exist "%DATA_ROOT%\tools" mkdir "%DATA_ROOT%\tools" 2>nul
if not exist "%DATA_ROOT%\tools" (
  echo Cannot write to %DATA_ROOT%\tools.>&2
  exit /b 4
)

set "WORK=%DATA_ROOT%\tools\.uv-download-%RANDOM%%RANDOM%"
mkdir "%WORK%" 2>nul
if not exist "%WORK%" (
  echo Cannot write to %DATA_ROOT%\tools.>&2
  exit /b 4
)

if "%MEMORYSAFE_UV_BASE_URL%"=="" set "MEMORYSAFE_UV_BASE_URL=https://github.com/astral-sh/uv/releases/download"
set "URL=%MEMORYSAFE_UV_BASE_URL%/%UV_VERSION%/!ARCHIVE_NAME!"

"%CURL%" --fail --silent --show-error --location --output "%WORK%\!ARCHIVE_NAME!" "!URL!" 1>&2
if errorlevel 1 (
  echo Could not download !URL!>&2
  rmdir /s /q "%WORK%" 2>nul
  exit /b 2
)

rem certutil prints a header, the digest, then a success line, redirected to a FILE -
rem never captured as a command's own output. This file no longer parses that output
rem at all, after four rounds of trying to and getting it wrong four different ways:
rem   1. Capturing via a single-quoted command string (no usebackq) whose first
rem      character, once %CERTUTIL% expanded, was a literal double quote. cmd.exe's
rem      for /f parser mishandled that and the loop ran zero times: ACTUAL stayed
rem      empty, and empty-vs-real-checksum was reported as a mismatch.
rem   2. Switching that same capture to usebackq with a backtick-quoted command runs
rem      the command through cmd /c, and cmd /c strips the outer quotes of a command
rem      line that begins with a literal double quote. That produced "The filename,
rem      directory name, or volume label syntax is incorrect" on a real windows-latest
rem      runner, and left ACTUAL holding parser leftovers (observed as a bare "=")
rem      instead of empty or a digest - again reported as a mismatch, because nothing
rem      checked ACTUAL's shape before comparing it.
rem   3. Reading certutil's stdout from a file (no command-capture) still did not
rem      yield a valid digest on a real windows-latest runner, for a reason nobody
rem      could see because the raw file was deleted before anyone could look at it.
rem      Fixed by dumping the raw file to stderr on failure (that dump stays, below)
rem      and adding a PowerShell fallback (that stays too).
rem   4. The dump then showed certutil exiting 0 with the byte-for-byte correct
rem      digest sitting right there in the file, while this file's own line-scanning
rem      parser (a nested `for %%c in (0 1 2 ... F)` stripping hex characters from a
rem      delayed-expansion variable, itself inside a per-line `for /f`) still decided
rem      no line was a valid digest. :dump_raw and :validate_digest read the exact
rem      same file with the same `for /f` primitive and disagreed - proof the defect
rem      was in the string-parsing machinery itself, not in which bytes were where.
rem The fix is to stop parsing the digest out of the file at all. certutil already
rem printed it; the only question is whether it equals EXPECTED, and findstr can
rem answer that without extracting anything: `findstr /c:"<expected>" file` succeeds
rem if and only if that exact string appears somewhere in the file. No for /f over
rem the digest text, no delayed-expansion substring surgery, no nested for, no
rem normalisation, no assumption about which line or byte holds what - the entire
rem class of bug this file has been fighting cannot occur here, because nothing here
rem reconstructs the digest as a string this file's own logic could get wrong.
rem
rem Soundness: matching EXPECTED anywhere in the tool's output is safe specifically
rem because that output cannot contain an attacker-chosen 64-hex-character string.
rem certutil's -hashfile output is exactly the path we asked it to hash (built from
rem our own %RANDOM%, inside our own data root, never from the downloaded archive's
rem contents) plus the digest it computed; Get-FileHash's output is nothing but the
rem digest itself. Neither tool ever echoes bytes from the file being hashed. Do not
rem "tighten" this back into a parser - that is exactly what kept failing.
set "POWERSHELL_RC=not attempted"
"%CERTUTIL%" -hashfile "%WORK%\!ARCHIVE_NAME!" SHA256 >"%WORK%\hash-certutil.txt" 2>&1
set "CERTUTIL_RC=!errorlevel!"
if !CERTUTIL_RC! neq 0 goto :try_powershell

rem certutil ran; ask findstr whether its output contains the expected digest. Do not
rem reorder certutil ahead of PowerShell - see the PowerShell block below for why.
call :verify_with_findstr "%WORK%\hash-certutil.txt"
if "!MATCH!"=="yes" (
  set "HASH_METHOD=certutil"
  goto :hash_verified
)
if "!MATCH!"=="no" goto :checksum_mismatch
rem MATCH=="error": certutil ran, but findstr itself did not behave as documented
rem (0 found / 1 not found). Fail closed the same way as a certutil that did not run
rem at all - fall through to the PowerShell fallback rather than guess.

:try_powershell
rem certutil is tried first because it needs no execution-policy exemption;
rem PowerShell is the fallback, not the default, because -ExecutionPolicy Bypass is a
rem broader ask on a locked-down machine. Do not reorder these.
rem
rem On a real windows-latest runner this failed with "Get-FileHash : The term
rem 'Get-FileHash' is not recognized...", exit 1 - most likely a constrained
rem PSModulePath preventing module auto-load in that environment. Now that certutil
rem is confirmed to work (see incident 4 above), this fallback is belt-and-braces
rem only, not load-bearing, and is left as-is rather than spending another cycle
rem chasing a secondary path.
"%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath '%WORK%\!ARCHIVE_NAME!').Hash" >"%WORK%\hash-powershell.txt" 2>&1
set "POWERSHELL_RC=!errorlevel!"
if !POWERSHELL_RC! neq 0 goto :neither_tool_verified
call :verify_with_findstr "%WORK%\hash-powershell.txt"
if "!MATCH!"=="yes" (
  set "HASH_METHOD=powershell"
  goto :hash_verified
)
if "!MATCH!"=="no" goto :checksum_mismatch
goto :neither_tool_verified

:checksum_mismatch
rem A real mismatch: the tool that produced this file ran successfully (exit 0), so
rem its output holds a genuine digest, and findstr confirms EXPECTED is not in it.
rem This is exit 3, never exit 1 - it is a fact about the download, not about this
rem script's tooling.
echo The downloaded uv did not match its recorded checksum for !ARCHIVE_NAME!. It was deleted and not run.>&2
echo   expected: !EXPECTED!>&2
echo --- certutil (exit !CERTUTIL_RC!) raw output: --->&2
call :dump_raw "%WORK%\hash-certutil.txt"
echo --- PowerShell (exit !POWERSHELL_RC!) raw output: --->&2
call :dump_raw "%WORK%\hash-powershell.txt"
echo ---------------------------------------------------->&2
del /f /q "%WORK%\!ARCHIVE_NAME!" 2>nul
rmdir /s /q "%WORK%" 2>nul
exit /b 3

:neither_tool_verified
rem Neither tool produced a result findstr could even check (bad exit code, or
rem findstr itself misbehaved on both). This is not a mismatch - nothing was
rem compared - so it is exit 1 ("anything else"), never exit 3. Never fall through
rem and run the archive unverified.
echo Could not verify !ARCHIVE_NAME! against its recorded checksum with certutil or PowerShell; nothing was verified or run.>&2
echo --- certutil (exit !CERTUTIL_RC!) raw output: --->&2
call :dump_raw "%WORK%\hash-certutil.txt"
echo --- PowerShell (exit !POWERSHELL_RC!) raw output: --->&2
call :dump_raw "%WORK%\hash-powershell.txt"
echo ------------------------------------------------------------------------>&2
del /f /q "%WORK%\!ARCHIVE_NAME!" 2>nul
rmdir /s /q "%WORK%" 2>nul
exit /b 1

:hash_verified
rem The Windows archive is flat - uv.exe, uvw.exe and uvx.exe sit at the root - so unlike
rem the POSIX tarball there is no leading directory to strip.
mkdir "%WORK%\publish" 2>nul
"%TAR%" -xf "%WORK%\!ARCHIVE_NAME!" -C "%WORK%\publish" 1>&2
if errorlevel 1 (
  rmdir /s /q "%WORK%" 2>nul
  echo Could not unpack !ARCHIVE_NAME!.>&2
  exit /b 2
)

rem Two launchers can race here on a first start. Whichever renames first wins, and the
rem other uses what it published.
if not exist "%TARGET_DIR%" move "%WORK%\publish" "%TARGET_DIR%" 1>nul 2>nul
rmdir /s /q "%WORK%" 2>nul

if not exist "%TARGET_DIR%\uv.exe" (
  echo Could not install uv into %TARGET_DIR%.>&2
  exit /b 4
)
echo %TARGET_DIR%\uv.exe
exit /b 0

rem --- Subroutines below this line only. Nothing above ever falls into them. ---

rem :verify_with_findstr <raw-hash-file>
rem Sets MATCH to "yes" if EXPECTED appears anywhere in the given file, "no" if
rem findstr ran cleanly and it does not, or "error" if findstr's own exit code was
rem something other than the documented 0 (found) / 1 (not found) - fail closed in
rem that case rather than guess which one it meant. See the big comment above this
rem file's two call sites for why matching EXPECTED as a substring, without parsing
rem or extracting anything, is both correct and sound here.
:verify_with_findstr
set "MATCH=error"
"%FINDSTR%" /i /c:"!EXPECTED!" "%~1" >nul 2>&1
if errorlevel 2 goto :eof
if errorlevel 1 (
  set "MATCH=no"
) else (
  set "MATCH=yes"
)
goto :eof

rem :dump_raw <file>
rem Prints a file's raw contents to stderr, capped at 5 lines so a pathological or
rem enormous file cannot flood the log, clearly delimited from the surrounding
rem messages. This is what a hashing-tool failure could never be diagnosed with
rem before: the raw file used to be deleted, with the rest of %WORK%, before anyone
rem could see what the tool had actually emitted.
:dump_raw
if not exist "%~1" (
  echo   ^(no output file^)>&2
  goto :eof
)
set "DUMP_N=0"
for /f "usebackq delims=" %%L in ("%~1") do (
  set /a DUMP_N+=1
  if !DUMP_N! leq 5 echo   %%L>&2
)
if "!DUMP_N!"=="0" echo   ^(file is empty^)>&2
if !DUMP_N! gtr 5 echo   ... ^(!DUMP_N! lines total, truncated^)>&2
goto :eof
