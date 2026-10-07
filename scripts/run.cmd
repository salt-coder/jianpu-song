@echo off
rem ============================================================
rem  Jianpu -> Music  (portable launcher)
rem  Usage:  run.cmd  "1 2 3 1|3 4 5-"  --engine sf2 --gm piano
rem          run.cmd  --demo list
rem          run.cmd  --help
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

set PY=
where python >nul 2>nul && set PY=python
if not defined PY ( where py >nul 2>nul && set PY=py -3 )

if not defined PY (
  echo.
  echo  [ERROR] Python not found.
  echo.
  echo  This package needs Python 3.8 or newer.
  echo  Download: https://www.python.org/downloads/
  echo  During install, CHECK the box: "Add python.exe to PATH"
  echo.
  pause
  exit /b 1
)

"%PY%" -X utf8 "%~dp03.py" %*

echo.
pause
