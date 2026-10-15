[CmdletBinding()]
param([ValidateSet("core", "full")][string]$Edition = "full")
# Builds a Windows download: a "Beat Sorter" folder with its own Python and
# every package already installed, plus "Beat Sorter.exe" to start it.
# Users unzip and double-click; no Python install needed.
#
#   -Edition core : scan / analyze (BPM + key) / organize / play / tag.
#                   No YouTube download, no Essentia vote. ~133 MB.
#   -Edition full : Core + YouTube download + Essentia key vote. ~206 MB.
#
# Runs on GitHub Actions (windows-latest) after actions/setup-python
# (Python 3.12) and ilammy/msvc-dev-cmd (the C compiler). Output:
#   dist\Beat Sorter\                       the app folder
#   dist\BeatSorter-Windows.zip             (full) or
#   dist\BeatSorter-Windows-Core.zip        (core)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
$dist = Join-Path $root "dist"
$app = Join-Path $dist "Beat Sorter"
$zipName = if ($Edition -eq "core") { "BeatSorter-Windows-Core.zip" } else { "BeatSorter-Windows.zip" }
$reqFile = Join-Path $root "packaging\requirements-$Edition.txt"
Write-Host "Building the $Edition edition -> $zipName"
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

# 2. The edition's packages, installed inside that Python
& $py -E -s -m ensurepip --default-pip
if ($LASTEXITCODE) { throw "ensurepip failed" }
& $py -E -s -m pip install --no-warn-script-location --disable-pip-version-check -r $reqFile
if ($LASTEXITCODE) { throw "Installing packages failed" }

# 3. Slim down site-packages (nothing here is needed to run; the full test
#    suite runs against this exact folder afterwards, so a needed file going
#    missing is caught).
$sp = "$app\python\Lib\site-packages"
# scikit-learn is a declared librosa dependency we never call. Drop the code,
# keep its dist-info so pip still considers the requirement satisfied.
Remove-Item "$sp\sklearn" -Recurse -Force -ErrorAction SilentlyContinue
# Build tools aren't used at runtime (the app never pip-installs on a bundled
# update -- see apply_update). pip stays, for manual repair.
foreach ($d in @("setuptools", "pkg_resources", "wheel", "_distutils_hack")) {
  Remove-Item "$sp\$d" -Recurse -Force -ErrorAction SilentlyContinue
}
Get-ChildItem $sp -Recurse -Directory |
  Where-Object { $_.Name -in @("tests", "test", "__pycache__") } |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
# Only compiled caches. NOT *.pyi: librosa loads its submodules through
# lazy_loader, which reads librosa\__init__.pyi at import time (removing the
# stubs broke `import librosa`; they're ~2 MB in total).
Get-ChildItem $sp -Recurse -File -Include *.pyc -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue
# distutils-precedence.pth would try to import the _distutils_hack we removed
Remove-Item "$sp\distutils-precedence.pth" -Force -ErrorAction SilentlyContinue

# 4. The app itself (same files the updater manages). The edition's
#    requirements ship as requirements.txt so an update doesn't think the
#    package set changed (and never pip-installs on a bundle).
robocopy "$root\beatsorter" "$app\beatsorter" /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copying the app failed" }
$global:LASTEXITCODE = 0
foreach ($f in @("README.txt", "CHANGELOG.txt", "LICENSE", "update.json") + `
         (Get-ChildItem "$root\*.bat" | ForEach-Object { $_.Name })) {
  Copy-Item (Join-Path $root $f) $app
}
Copy-Item $reqFile "$app\requirements.txt"
Set-Content "$app\edition.txt" $Edition -NoNewline

# 5. Beat Sorter.exe (starts python\pythonw.exe -m beatsorter, with the icon)
Push-Location $PSScriptRoot
rc /nologo /fo launcher.res launcher.rc
if ($LASTEXITCODE) { throw "rc failed" }
cl /nologo /O2 /W3 launcher.c launcher.res /Fe:"$app\Beat Sorter.exe" /link /SUBSYSTEM:WINDOWS user32.lib
if ($LASTEXITCODE) { throw "Compiling the launcher failed" }
Remove-Item launcher.obj, launcher.res -ErrorAction SilentlyContinue
Pop-Location

# 6. Precompile the app (small) so the first start is quick. The stdlib
#    compiles itself on first import; shipping its .pyc too would nearly
#    double its size on disk.
& $py -E -s -m compileall -q "$app\beatsorter" | Out-Null
$global:LASTEXITCODE = 0

# 7. The zip users download (one "Beat Sorter" folder inside, standard ZIP so
#    Windows Explorer opens it with no extra tool).
Push-Location $dist
7z a -tzip -mx=9 $zipName "Beat Sorter" | Out-Null
if ($LASTEXITCODE) { throw "Zipping failed" }
Pop-Location
$mb = [math]::Round((Get-Item "$dist\$zipName").Length / 1MB)
$folder = [math]::Round((Get-ChildItem $app -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
$bytes = (Get-Item "$dist\$zipName").Length
Write-Host "Built dist\$zipName ($Edition): $mb MB download, $folder MB unzipped"
# Shown as an annotation on the run summary (readable without the logs)
Write-Host "::notice title=$Edition size::$zipName = $bytes bytes ($([math]::Round($bytes / 1MB, 1)) MiB zipped, $folder MiB unzipped)"
