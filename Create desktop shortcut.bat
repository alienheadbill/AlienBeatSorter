@echo off
rem Puts a "Beat Sorter" shortcut with the alien-head icon on your desktop.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = (Get-Location).Path; $s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath(Desktop) + \Beat Sorter.lnk); $s.TargetPath = $d + \.venv\Scripts\pythonw.exe; $s.Arguments = -m beatsorter; $s.WorkingDirectory = $d; $s.IconLocation = $d + \beatsorter\assets\beatsorter.ico; $s.Save()"
if errorlevel 1 ( echo Could not create the shortcut. & pause & exit /b 1 )
echo Shortcut created on your desktop.
pause
