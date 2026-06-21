@echo off
REM Double-clickable launcher for the Elichika menu on Windows.
REM
REM Double-clicking a .cmd runs it in cmd.exe. The menu is a bash script, so we
REM locate Git Bash (installed together with Git for Windows by the installer)
REM and use it to run the menu from this folder. Works regardless of where the
REM install lives, because cd /d "%~dp0" jumps to this file's own folder first.
setlocal
cd /d "%~dp0"

set "BASH="
if exist "%ProgramFiles%\Git\bin\bash.exe" set "BASH=%ProgramFiles%\Git\bin\bash.exe"
if not defined BASH if exist "%ProgramFiles%\Git\usr\bin\bash.exe" set "BASH=%ProgramFiles%\Git\usr\bin\bash.exe"
if not defined BASH if exist "%ProgramFiles(x86)%\Git\bin\bash.exe" set "BASH=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not defined BASH if exist "%LocalAppData%\Programs\Git\bin\bash.exe" set "BASH=%LocalAppData%\Programs\Git\bin\bash.exe"
if not defined BASH for /f "delims=" %%B in ('where bash 2^>nul') do if not defined BASH set "BASH=%%B"

if defined BASH (
  "%BASH%" elichika_utility.sh
) else (
  echo Could not find Git Bash.
  echo Install Git for Windows from https://git-scm.com/download/win and try again.
  pause
)
