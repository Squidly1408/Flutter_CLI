$ErrorActionPreference = 'Stop'

Write-Host 'Building FlutterDevLauncher Windows executable...'

if (-not (Test-Path '.venv')) {
    Write-Host 'No .venv found. Using system Python environment.'
}

pyinstaller --clean --noconfirm FlutterDevLauncher.spec

Write-Host ''
Write-Host 'Build complete.'
Write-Host 'Executable: dist\\FlutterDevLauncher.exe'
