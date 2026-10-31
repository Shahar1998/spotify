$ErrorActionPreference = "Stop"

$iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    $known_paths = @(
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $known_path = $known_paths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($known_path) {
        $iscc = @{ Source = $known_path }
    }
}
if (-not $iscc) {
    throw "Inno Setup was not found. Install Inno Setup, or add ISCC.exe to PATH."
}

if (-not (Test-Path ".\dist\SpotiWord\SpotiWord.exe")) {
    throw "Build the application first with build.ps1."
}

& $iscc.Source ".\installer.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE."
}

Write-Host "Installer created in .\installer"
