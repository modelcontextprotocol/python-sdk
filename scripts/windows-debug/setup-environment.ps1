#!/usr/bin/env pwsh
# Script to set up the environment for running stdio tests on Windows
# This adds Git for Windows tools to PATH if available
# Usage: . .\setup-environment.ps1 (note the dot-sourcing)

Write-Host "Setting up environment for stdio tests..." -ForegroundColor Cyan
Write-Host ""

# Check if Git for Windows is installed
$gitPaths = @(
    "C:\Program Files\Git\usr\bin",
    "C:\Program Files (x86)\Git\usr\bin"
)

$gitFound = $false
$gitPath = ""

foreach ($path in $gitPaths) {
    if (Test-Path $path) {
        $gitPath = $path
        $gitFound = $true
        break
    }
}

if ($gitFound) {
    Write-Host "Found Git for Windows at: $gitPath" -ForegroundColor Green
    
    # Add to PATH
    $env:PATH = "$gitPath;$env:PATH"
    
    # Verify tee is available
    $teeCheck = python -c "import shutil; print(shutil.which('tee'))"
    if ($teeCheck -and $teeCheck -ne "None") {
        Write-Host "Successfully added tee to PATH: $teeCheck" -ForegroundColor Green
        Write-Host ""
        Write-Host "Environment is ready for stdio tests!" -ForegroundColor Green
        Write-Host ""
        Write-Host "You can now run the test scripts or individual tests:" -ForegroundColor Cyan
        Write-Host "  .\test-stdio-flakiness-200-runs.ps1"
        Write-Host "  .\test-stdio-flakiness-until-failure.ps1"
        Write-Host "  .\test-stdio-verbose-debug.ps1"
        Write-Host ""
        Write-Host "Or run individual tests with:" -ForegroundColor Cyan
        Write-Host "  uv run pytest tests/client/test_stdio.py::test_stdio_context_manager_exiting -v -o addopts="""""
    } else {
        Write-Host "WARNING: Git path was added but tee is still not available" -ForegroundColor Yellow
    }
} else {
    Write-Host "Git for Windows not found in standard locations." -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Git for Windows from: https://gitforwindows.org/" -ForegroundColor Yellow
    Write-Host "Or manually add the Git usr\bin directory to your PATH." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Note: This only affects the current PowerShell session." -ForegroundColor Gray
Write-Host "To make changes permanent, add to your PowerShell profile:" -ForegroundColor Gray
Write-Host '  $env:PATH = "C:\Program Files\Git\usr\bin;$env:PATH"' -ForegroundColor Cyan