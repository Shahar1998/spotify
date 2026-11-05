$ErrorActionPreference = "Stop"

Write-Host "Building SpotiWord Windows application..."
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Project virtual environment not found. Create .venv and install requirements first."
}

& $python -m PyInstaller --noconfirm --clean --windowed --name SpotiWord --add-data "$PSScriptRoot\assets\spotiword.svg;assets" --collect-data langdetect gui_app.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

Copy-Item -LiteralPath ".env.example" -Destination ".\dist\SpotiWord\.env.example" -Force

Write-Host "Build complete: dist\\SpotiWord\\SpotiWord.exe"
