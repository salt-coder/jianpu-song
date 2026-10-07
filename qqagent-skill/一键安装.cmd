@echo off
rem ============================================================
rem  Jianpu Song skill  -  installer for QQ Agent
rem  Installs:  skills\jianpu-song\   +   jianpu-tools\
rem  into:      <QQ Agent>\resources\app\
rem ============================================================
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   Jianpu Song skill installer for QQ Agent
echo ============================================
echo.

if not exist "skills\jianpu-song\skill.json" (
  echo [ERROR] skills\jianpu-song\skill.json not found.
  echo         Please extract the whole zip first, then run this script.
  pause
  exit /b 1
)
if not exist "jianpu-tools\3.py" (
  echo [ERROR] jianpu-tools\3.py not found.
  echo         Please extract the whole zip first, then run this script.
  pause
  exit /b 1
)

set "APP="

rem --- 1) common install locations ---
for %%D in (
  "%LOCALAPPDATA%\Programs\QQ Agent\resources\app"
  "%LOCALAPPDATA%\QQ Agent\resources\app"
  "%LOCALAPPDATA%\Programs\qq-agent\resources\app"
  "%PROGRAMFILES%\QQ Agent\resources\app"
  "D:\QQ Agent\resources\app"
  "E:\QQ Agent\resources\app"
) do (
  if not defined APP if exist "%%~D\package.json" set "APP=%%~D"
)

rem --- 2) ask the running process where it lives ---
if not defined APP (
  for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$p=Get-Process 'QQ Agent' -ErrorAction SilentlyContinue ^| Select-Object -First 1; if($p){Split-Path -Parent $p.Path}"`) do (
    if not defined APP if exist "%%P\resources\app\package.json" set "APP=%%P\resources\app"
  )
)

if not defined APP (
  echo [ERROR] Could not find QQ Agent automatically.
  echo.
  echo Please install manually - see 安装说明.md section "方式 B".
  echo   copy  skills\jianpu-song   to  ^<QQ Agent^>\resources\app\skills\
  echo   copy  jianpu-tools         to  ^<QQ Agent^>\resources\app\
  echo.
  pause
  exit /b 1
)

echo Found QQ Agent at:
echo   %APP%
echo.
echo [1/2] Copying skill ...
if not exist "%APP%\skills" mkdir "%APP%\skills" >nul 2>nul
xcopy /e /i /y "skills\jianpu-song" "%APP%\skills\jianpu-song" >nul
if errorlevel 1 goto fail

echo [2/2] Copying toolchain (about 205 MB, please wait 10-60s) ...
xcopy /e /i /y "jianpu-tools" "%APP%\jianpu-tools" >nul
if errorlevel 1 goto fail

echo.
echo ============================================
echo   Done!
echo ============================================
echo   Next:
echo     1. Open QQ Agent console
echo     2. Click the "Skills" tab (NOT "Plugins")
echo     3. You should see:  Jianpu Song  (简谱点歌)
echo     4. Send  1166556  in a group chat to test
echo.
echo   Hot reload is on - no restart needed.
echo.
pause
exit /b 0

:fail
echo.
echo [ERROR] Copy failed. Try running this script as Administrator,
echo         or close QQ Agent first and run again.
pause
exit /b 1
