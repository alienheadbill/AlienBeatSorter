@echo off
rem Same as Beat Sorter.bat but keeps a console window open, so errors are visible.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m beatsorter
pause
