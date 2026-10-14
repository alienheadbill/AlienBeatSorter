@echo off
setlocal
cd /d "%~dp0"
if exist "python\python.exe" (
  echo This copy of Beat Sorter already includes everything it needs.
  echo No setup is needed: just double-click "Beat Sorter.exe".
  echo.
  pause
  exit /b 0
)
echo.
echo === Beat Sorter setup ===
echo.
set "PY="
for %%V in (3.12 3.13 3.11 3.10) do (
  if not defined PY (
    py -%%V -c "import tkinter" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys, tkinter; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Could not find a compatible Python ^(3.10 to 3.13^).
  echo.
  echo Install Python 3.12 from https://www.python.org/downloads/windows/
  echo During install, tick "Add python.exe to PATH". Then run setup.bat again.
  echo.
  pause
  exit /b 1
)
echo Using: %PY%
if exist .venv rmdir /s /q .venv
%PY% -m venv .venv
if errorlevel 1 ( echo Could not create the environment. & pause & exit /b 1 )
echo Installing audio libraries ^(this can take a few minutes^)...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 ( echo Install failed. See the messages above. & pause & exit /b 1 )
echo.
echo Setup complete. Double-click "Beat Sorter.bat" to start.
echo.
pause
