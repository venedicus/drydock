@echo off
rem Drydock.
rem   без аргументов  -- окно приложения (pythonw, без консоли)
rem   с аргументами -- CLI: Drydock.bat status ^| scan ^| probe ^| archive
cd /d "%~dp0"
if "%~1"=="" (
  start "" ".venv\Scripts\pythonw.exe" -m drydock.cli app
) else (
  ".venv\Scripts\python.exe" -m drydock.cli %*
)
