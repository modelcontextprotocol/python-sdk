#!/usr/bin/env pwsh
# Simple script to run the test without xdist
# Usage: .\test-stdio-simple.ps1

Write-Host "Running test_stdio_context_manager_exiting with xdist disabled..." -ForegroundColor Cyan
Write-Host ""

# Method 1: Using environment variable (recommended in CLAUDE.md)
Write-Host "Method 1: Using PYTEST_DISABLE_PLUGIN_AUTOLOAD environment variable" -ForegroundColor Yellow
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = ""
uv run --frozen pytest tests/client/test_stdio.py::test_stdio_context_manager_exiting -xvs
$exitCode1 = $LASTEXITCODE
Remove-Item Env:PYTEST_DISABLE_PLUGIN_AUTOLOAD -ErrorAction SilentlyContinue

if ($exitCode1 -eq 0) {
    Write-Host "Method 1: PASSED" -ForegroundColor Green
} else {
    Write-Host "Method 1: FAILED with exit code $exitCode1" -ForegroundColor Red
}

Write-Host ""

# Method 2: Using -p no:xdist to disable the plugin
Write-Host "Method 2: Using -p no:xdist flag" -ForegroundColor Yellow
uv run --frozen pytest tests/client/test_stdio.py::test_stdio_context_manager_exiting -xvs -p no:xdist
$exitCode2 = $LASTEXITCODE

if ($exitCode2 -eq 0) {
    Write-Host "Method 2: PASSED" -ForegroundColor Green
} else {
    Write-Host "Method 2: FAILED with exit code $exitCode2" -ForegroundColor Red
}

Write-Host ""

# Method 3: Override addopts from pyproject.toml
Write-Host "Method 3: Overriding pytest addopts" -ForegroundColor Yellow
uv run --frozen pytest tests/client/test_stdio.py::test_stdio_context_manager_exiting -xvs -o addopts=""
$exitCode3 = $LASTEXITCODE

if ($exitCode3 -eq 0) {
    Write-Host "Method 3: PASSED" -ForegroundColor Green
} else {
    Write-Host "Method 3: FAILED with exit code $exitCode3" -ForegroundColor Red
}

Write-Host ""
Write-Host "========== SUMMARY ==========" -ForegroundColor Cyan
if ($exitCode1 -eq 0 -or $exitCode2 -eq 0 -or $exitCode3 -eq 0) {
    Write-Host "At least one method succeeded!" -ForegroundColor Green
    Write-Host "Use the successful method in your testing."
} else {
    Write-Host "All methods failed. The test may have a different issue." -ForegroundColor Red
}