@echo off
cd /d "%~dp0"
if exist "python\pythonw.exe" (
  rem Windows download: Python is included
  start "" "python\pythonw.exe" -E -s -m beatsorter
  exit /b 0
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo Beat Sorter is not set up yet. Run setup.bat first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m beatsorter
