[CmdletBinding()]
param([ValidateSet("core", "full")][string]$Edition = "full")
# Tests a Windows download the way a user gets it, on a PC with no Python:
# unzip into a folder with spaces, start it with "Beat Sorter.exe", check the
# edition's feature matrix, then run the whole test suite with the bundled
# Python.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
$zipName = if ($Edition -eq "core") { "BeatSorter-Windows-Core.zip" } else { "BeatSorter-Windows.zip" }
$zip = Join-Path $root "dist\$zipName"
$base = Join-Path $env:RUNNER_TEMP "Test $Edition (with spaces)"
if (Test-Path $base) { Remove-Item $base -Recurse -Force }
New-Item -ItemType Directory $base | Out-Null
7z x $zip "-o$base" | Out-Null
if ($LASTEXITCODE) { throw "Unzipping failed" }
$app = Join-Path $base "Beat Sorter"
$py = Join-Path $app "python\python.exe"

# No Python on PATH: only Windows itself
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
$env:LOCALAPPDATA = Join-Path $env:RUNNER_TEMP "bundle-appdata-$Edition"
Remove-Item Env:PYTHONPATH, Env:PYTHONHOME -ErrorAction SilentlyContinue
if (Get-Command python -ErrorAction SilentlyContinue) { throw "python is still on PATH" }

# edition.txt and requirements.txt ship with the bundle
if ((Get-Content "$app\edition.txt" -Raw).Trim() -ne $Edition) { throw "edition.txt wrong" }
if (-not (Test-Path "$app\requirements.txt")) { throw "requirements.txt missing from bundle" }
$req = Get-Content "$app\requirements.txt" -Raw
if ($Edition -eq "core" -and $req -match "deno") { throw "Core requirements.txt must not list deno" }

Write-Host "Checking the $Edition feature matrix"
# Always present: analysis stack + playback. Optional present only in Full.
$check = @'
import importlib.util, sys
edition = sys.argv[1]
def have(m): return importlib.util.find_spec(m) is not None
# required everywhere
for m in ["librosa", "numba", "llvmlite", "numpy", "scipy", "soundfile", "sounddevice", "tkinterdnd2"]:
    assert have(m), f"missing required module: {m}"
# BPM + key detection must actually run
import numpy as np
from beatsorter import analyzer
t = np.arange(44100*4)/44100
y = (0.2*(np.sin(2*np.pi*220*t)+np.sin(2*np.pi*261.63*t)+np.sin(2*np.pi*329.63*t))).astype("float32")
assert analyzer.detect_bpm(y, 44100)["bpm"] > 0, "BPM detection failed"
assert analyzer.detect_key(y)["key_pc"] >= 0, "key detection failed"
# scikit-learn is stripped from both
assert not have("sklearn"), "scikit-learn should be stripped"
# optional features
opt = ["yt_dlp", "imageio_ffmpeg", "deno"]
from beatsorter import essentiakey, downloader
if edition == "full":
    for m in opt: assert have(m), f"Full is missing optional module: {m}"
    assert essentiakey.available(), "Full should have Essentia (deno)"
    assert downloader.available()[0], "Full should have the downloader"
else:
    for m in opt: assert not have(m), f"Core must not ship optional module: {m}"
    assert not essentiakey.available(), "Core must not have Essentia"
    assert downloader.available()[0] is False, "Core must report downloader unavailable"
print(f"{edition} feature matrix OK")
'@
$check | & $py -E -s - $Edition
if ($LASTEXITCODE) { throw "Feature matrix check failed" }

Write-Host "Starting Beat Sorter.exe --smoke-test"
$p = Start-Process -FilePath (Join-Path $app "Beat Sorter.exe") -ArgumentList "--smoke-test" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Beat Sorter.exe smoke test failed (exit $($p.ExitCode))" }
Write-Host "Beat Sorter.exe opened and closed cleanly"

# The full test suite, run by the bundled Python against the bundled packages
$pt = Join-Path $env:RUNNER_TEMP "pytest-only-$Edition"
& $py -E -s -m pip install --quiet --disable-pip-version-check --target $pt pytest pytest-github-actions-annotate-failures
if ($LASTEXITCODE) { throw "Couldn't install pytest for the test run" }
Push-Location $root
& $py -E -s -c "import sys; sys.path[:0] = [r'$pt', r'$app', r'$root']; import pytest; sys.exit(pytest.main(['-v', '-p', 'pytest_github_actions_annotate_failures', r'$root\tests']))"
$code = $LASTEXITCODE
Pop-Location
if ($code) { throw "Tests failed with the bundled Python (exit $code)" }
Write-Host "All tests passed with the bundled $Edition Python"
