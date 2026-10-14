@echo off
rem Same as Beat Sorter.bat but keeps a console window open, so errors are visible.
cd /d "%~dp0"
if exist "python\python.exe" (
  "python\python.exe" -E -s -m beatsorter
) else (
  ".venv\Scripts\python.exe" -m beatsorter
)
pause
