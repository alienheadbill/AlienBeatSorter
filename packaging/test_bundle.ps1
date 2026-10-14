# Tests the Windows download the way a user gets it, on a PC with no
# Python: unzip into a folder with spaces in its name, start it with
# "Beat Sorter.exe", then run the whole test suite with the bundled Python.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
$zip = Join-Path $root "dist\BeatSorter-Windows.zip"
$base = Join-Path $env:RUNNER_TEMP "Test Folder (with spaces)"
if (Test-Path $base) { Remove-Item $base -Recurse -Force }
New-Item -ItemType Directory $base | Out-Null
7z x $zip "-o$base" | Out-Null
if ($LASTEXITCODE) { throw "Unzipping failed" }
$app = Join-Path $base "Beat Sorter"
$py = Join-Path $app "python\python.exe"

# No Python on PATH: only Windows itself
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
$env:LOCALAPPDATA = Join-Path $env:RUNNER_TEMP "bundle-appdata"
Remove-Item Env:PYTHONPATH, Env:PYTHONHOME -ErrorAction SilentlyContinue
if (Get-Command python -ErrorAction SilentlyContinue) { throw "python is still on PATH" }

Write-Host "Starting Beat Sorter.exe --smoke-test"
$p = Start-Process -FilePath (Join-Path $app "Beat Sorter.exe") -ArgumentList "--smoke-test" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Beat Sorter.exe smoke test failed (exit $($p.ExitCode))" }
Write-Host "Beat Sorter.exe opened and closed cleanly"

# The full test suite, run by the bundled Python against the bundled packages
$pt = Join-Path $env:RUNNER_TEMP "pytest-only"
& $py -E -s -m pip install --quiet --disable-pip-version-check --target $pt pytest pytest-github-actions-annotate-failures
if ($LASTEXITCODE) { throw "Couldn't install pytest for the test run" }
Push-Location $root
& $py -E -s -c "import sys; sys.path[:0] = [r'$pt', r'$app', r'$root']; import pytest; sys.exit(pytest.main(['-v', '-p', 'pytest_github_actions_annotate_failures', r'$root\tests']))"
$code = $LASTEXITCODE
Pop-Location
if ($code) { throw "Tests failed with the bundled Python (exit $code)" }
Write-Host "All tests passed with the bundled Python"
