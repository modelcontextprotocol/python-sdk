#!/usr/bin/env pwsh
# Simple script to run the test without xdist
# Usage: .\test-stdio-simple.ps1
#
# Prerequisites: Run . .\setup-environment.ps1 first to ensure tee is available

Write-Host "Running test_stdio_context_manager_exiting with xdist disabled..." -ForegroundColor Cyan
Write-Host ""

# Check if tee is available
$teeCheck = python -c "import shutil; print(shutil.which('tee'))"
if (-not $teeCheck -or $teeCheck -eq "None") {
    Write-Host "ERROR: tee command not found!" -ForegroundColor Red
    Write-Host "Please run: . .\setup-environment.ps1" -ForegroundColor Yellow
    Write-Host "(Note the dot at the beginning to source the script)" -ForegroundColor Yellow
    exit 1
}

Write-Host "tee found at: $teeCheck" -ForegroundColor Green
Write-Host ""

# Run the test with the working method
Write-Host "Running test with -o addopts='' to override xdist..." -ForegroundColor Yellow
uv run --frozen pytest tests/client/test_stdio.py::test_stdio_context_manager_exiting -xvs -o addopts=""
$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "Test PASSED!" -ForegroundColor Green
    Write-Host ""
    Write-Host "You can now use the other scripts to test for flakiness:" -ForegroundColor Cyan
    Write-Host "  .\test-stdio-flakiness-200-runs.ps1" 
    Write-Host "  .\test-stdio-flakiness-until-failure.ps1"
    Write-Host "  .\test-stdio-verbose-debug.ps1"
} else {
    Write-Host "Test FAILED with exit code $exitCode" -ForegroundColor Red
    Write-Host ""
    Write-Host "Try running with verbose debug:" -ForegroundColor Yellow
    Write-Host "  .\test-stdio-verbose-debug.ps1"
}