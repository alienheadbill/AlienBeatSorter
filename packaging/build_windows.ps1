# Builds the Windows download: a "Beat Sorter" folder with its own Python
# and every package already installed, plus "Beat Sorter.exe" to start it.
# Users unzip and double-click; no Python install needed.
#
# Runs on GitHub Actions (windows-latest) after actions/setup-python
# (Python 3.12) and ilammy/msvc-dev-cmd (the C compiler). Output:
#   dist\Beat Sorter\            the app folder
#   dist\BeatSorter-Windows.zip  what users download
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
$dist = Join-Path $root "dist"
$app = Join-Path $dist "Beat Sorter"
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
New-Item -ItemType Directory $app | Out-Null

# 1. A private copy of Python (without its tests, docs and build tools)
$pyhome = (python -c "import sys; print(sys.base_prefix)").Trim()
Write-Host "Copying Python from $pyhome"
robocopy $pyhome "$app\python" /E /NFL /NDL /NJH /NJS /NP `
  /XD "$pyhome\Lib\test" "$pyhome\Lib\site-packages" "$pyhome\Doc" "$pyhome\Tools" `
      "$pyhome\include" "$pyhome\libs" "$pyhome\Scripts" "$pyhome\Lib\idlelib\idle_test" __pycache__ | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copying Python failed ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0
New-Item -ItemType Directory "$app\python\Lib\site-packages" -Force | Out-Null
$py = "$app\python\python.exe"

# 2. Beat Sorter's packages, installed inside that Python (pip stays
#    included: the in-app updater uses it if packages ever change)
& $py -E -s -m ensurepip --default-pip
if ($LASTEXITCODE) { throw "ensurepip failed" }
& $py -E -s -m pip install --no-warn-script-location --disable-pip-version-check -r "$root\requirements.txt"
if ($LASTEXITCODE) { throw "Installing packages failed" }

# 3. Slim it down: package test folders aren't needed to run (the full
#    test suite runs against this exact folder afterwards, so a needed
#    file going missing would be caught)
Get-ChildItem "$app\python\Lib\site-packages" -Recurse -Directory -Filter tests |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 4. The app itself (same files the updater manages)
robocopy "$root\beatsorter" "$app\beatsorter" /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copying the app failed" }
$global:LASTEXITCODE = 0
foreach ($f in @("README.txt", "CHANGELOG.txt", "LICENSE", "update.json") + `
         (Get-ChildItem "$root\*.bat" | ForEach-Object { $_.Name })) {
  Copy-Item (Join-Path $root $f) $app
}

# 5. Beat Sorter.exe (starts python\pythonw.exe -m beatsorter, with the icon)
Push-Location $PSScriptRoot
rc /nologo /fo launcher.res launcher.rc
if ($LASTEXITCODE) { throw "rc failed" }
cl /nologo /O2 /W3 launcher.c launcher.res /Fe:"$app\Beat Sorter.exe" /link /SUBSYSTEM:WINDOWS user32.lib
if ($LASTEXITCODE) { throw "Compiling the launcher failed" }
Remove-Item launcher.obj, launcher.res -ErrorAction SilentlyContinue
Pop-Location

# 6. Precompile so the first start is quick
& $py -E -s -m compileall -q -j 0 "$app\beatsorter" "$app\python\Lib" | Out-Null
$global:LASTEXITCODE = 0

# 7. The zip users download (one "Beat Sorter" folder inside)
Push-Location $dist
7z a -tzip -mx=7 BeatSorter-Windows.zip "Beat Sorter" | Out-Null
if ($LASTEXITCODE) { throw "Zipping failed" }
Pop-Location
$mb = [math]::Round((Get-Item "$dist\BeatSorter-Windows.zip").Length / 1MB)
$folder = [math]::Round((Get-ChildItem $app -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "Built dist\BeatSorter-Windows.zip: $mb MB download, $folder MB unzipped"
