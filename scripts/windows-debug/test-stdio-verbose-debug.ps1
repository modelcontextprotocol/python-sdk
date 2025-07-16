#!/usr/bin/env pwsh
# Script to run test_stdio_context_manager_exiting with maximum debugging output
# Usage: .\test-stdio-verbose-debug.ps1

Write-Host "Running test_stdio_context_manager_exiting with verbose debug output..." -ForegroundColor Cyan
Write-Host ""

# Set environment variables for debugging
$env:PYTHONFAULTHANDLER = "1"
$env:PYTEST_CURRENT_TEST = "1"

Write-Host "Environment variables set:" -ForegroundColor Yellow
Write-Host "  PYTHONFAULTHANDLER = 1 (enables Python fault handler)"
Write-Host ""

Write-Host "Running test with maximum verbosity..." -ForegroundColor Cyan
Write-Host ""

# Run the test with all debugging options
uv run --frozen pytest `
    tests/client/test_stdio.py::test_stdio_context_manager_exiting `
    -xvs `
    -n 0 `
    --log-cli-level=DEBUG `
    --log-cli-format="%(asctime)s [%(levelname)s] %(name)s: %(message)s" `
    --capture=no `
    --tb=long `
    --full-trace

$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "Test PASSED" -ForegroundColor Green
} else {
    Write-Host "Test FAILED with exit code: $exitCode" -ForegroundColor Red
}

# Clean up environment variables
Remove-Item Env:PYTHONFAULTHANDLER -ErrorAction SilentlyContinue
Remove-Item Env:PYTEST_CURRENT_TEST -ErrorAction SilentlyContinue