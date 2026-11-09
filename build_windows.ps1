# Run from an activated 64-bit Python 3.11 environment on Windows 10/11.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$buildLog = Join-Path $PSScriptRoot 'build_windows.log'
$portableZip = Join-Path $PSScriptRoot 'AI-CAD-Windows-Portable.zip'
$distDir = Join-Path $PSScriptRoot 'dist\AI-CAD'
$exe = Join-Path $distDir 'AI-CAD.exe'
$smokeDir = Join-Path $distDir 'smoke'
$transcribing = $false

try {
    Start-Transcript -Path $buildLog -Force | Out-Null
    $transcribing = $true
    Write-Host 'AI-CAD Windows x64 release build'

    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw 'Python not found. Activate the Python 3.11 x64 environment.'
    }
    & python -c "import sys, struct; assert sys.platform == 'win32' and sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8, 'Requires Windows x64 and Python 3.11'"
    if ($LASTEXITCODE -ne 0) { throw 'Wrong OS, Python version or architecture.' }
    & python -c "import cadquery, OCP, PySide6, shiboken6, PyInstaller, requests, reportlab, ezdxf, certifi; from PySide6.QtCore import QLibraryInfo; from pathlib import Path; p=Path(QLibraryInfo.path(QLibraryInfo.PluginsPath))/'platforms'/'qwindows.dll'; assert p.is_file(), 'Qt Windows platform plugin missing'; print('Dependencies and Qt Windows plugin OK:', p)"
    if ($LASTEXITCODE -ne 0) { throw 'Missing dependency or Qt qwindows.dll plugin.' }

    & python -m unittest discover -s tests -p 'test_project_unittest.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Legacy tests failed.' }
    & python -m unittest discover -s tests -p 'test_universal.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Universal CAD tests failed.' }
    & python -m unittest discover -s tests -p 'test_mistral_integration.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Mocked Mistral tests failed.' }
    & python -m unittest discover -s tests -p 'test_topology_assembly.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Topology and assembly tests failed.' }
    & python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Full pytest suite failed.' }

    # Remove generated outputs so a stale EXE or archive cannot pass verification.
    if (Test-Path $distDir) { Remove-Item $distDir -Recurse -Force }
    if (Test-Path $portableZip) { Remove-Item $portableZip -Force }

    $pyinstallerArgs = @(
        '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
        '--name', 'AI-CAD', '--contents-directory', '_internal',
        '--collect-all', 'cadquery', '--collect-all', 'OCP',
        # Qt modules/plugins are discovered from actual imports by PyInstaller hooks.
        # Do NOT collect-all PySide6: that pulls QtWebEngine and missing qtwebengine_locales.
        '--collect-all', 'ezdxf', '--collect-all', 'reportlab',
        '--collect-all', 'requests', '--collect-all', 'certifi',
        # The CAD desktop UI does not import QtWebEngine; exclude its heavy hooks.
        '--exclude-module', 'PySide6.QtWebEngineCore',
        '--exclude-module', 'PySide6.QtWebEngineWidgets',
        '--exclude-module', 'PySide6.QtWebEngineQuick',
        '--exclude-module', 'PySide6.QtWebChannel'
    )
    # conda-forge OpenCascade DLLs may live outside OCP's Python package.
    if ($env:CONDA_PREFIX) {
        $condaBin = Join-Path $env:CONDA_PREFIX 'Library\bin'
        if ((Test-Path $condaBin) -and (Get-ChildItem $condaBin -Filter 'TK*.dll' -File | Select-Object -First 1)) {
            $pyinstallerArgs += @('--add-binary', ((Join-Path $condaBin 'TK*.dll') + ';.'))
            Write-Host 'Including conda-forge OpenCascade DLLs.'
        }
    }
    $pyinstallerArgs += 'run.py'
    & python @pyinstallerArgs
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    if (-not (Test-Path $exe)) { throw 'AI-CAD.exe was not created.' }

    # The frozen process must import OCP/Qt, build geometry, save/reload,
    # export/reimport STEP, render a viewport and construct the main GUI.
    & $exe --smoke-test $smokeDir
    if ($LASTEXITCODE -ne 0) { throw 'Packaged EXE smoke test failed.' }
    $reportPath = Join-Path $smokeDir 'report.json'
    if (-not (Test-Path $reportPath)) { throw 'Smoke report missing.' }
    $report = Get-Content $reportPath -Raw | ConvertFrom-Json
    if ($report.status -ne 'ok' -or $report.feature_count -lt 3 -or $report.assembly_solids -ne 2) {
        throw 'Packaged EXE reported incomplete CAD validation.'
    }
    foreach ($name in @('viewport.png', 'main_window.png', 'smoke.step', 'smoke.stl', 'smoke.aicad.json')) {
        $file = Join-Path $smokeDir $name
        if (-not (Test-Path $file) -or (Get-Item $file).Length -lt 100) {
            throw "Missing or empty packaged smoke artifact: $name"
        }
    }

    Compress-Archive -Path $distDir -DestinationPath $portableZip -Force
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zipReader = [System.IO.Compression.ZipFile]::OpenRead($portableZip)
    try {
        $exeEntry = $zipReader.Entries | Where-Object { $_.FullName.Replace('\', '/') -eq 'AI-CAD/AI-CAD.exe' } | Select-Object -First 1
        if (-not $exeEntry -or $exeEntry.Length -lt 100) { throw 'Portable archive does not contain AI-CAD.exe.' }
    }
    finally { $zipReader.Dispose() }
    Write-Host "SUCCESS: $exe"
    Write-Host "PORTABLE ZIP: $portableZip"
    Write-Host "SMOKE REPORT: $reportPath"
    Write-Host 'Perform the manual GUI workflow on the demonstration PC before presenting.'
}
finally {
    if ($transcribing) { Stop-Transcript | Out-Null }
}
