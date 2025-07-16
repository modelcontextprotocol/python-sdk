#!/usr/bin/env pwsh
# Script to run test_stdio_context_manager_exiting 200 times to detect flakiness
# Usage: .\test-stdio-flakiness-200-runs.ps1
#
# Prerequisites: Run . .\setup-environment.ps1 first to ensure tee is available

Write-Host "Running test_stdio_context_manager_exiting 200 times to detect flakiness..." -ForegroundColor Cyan
Write-Host "Test: tests/client/test_stdio.py::test_stdio_context_manager_exiting" -ForegroundColor Yellow
Write-Host ""

# Check if tee is available
$teeCheck = python -c "import shutil; print(shutil.which('tee'))"
if (-not $teeCheck -or $teeCheck -eq "None") {
    Write-Host "ERROR: tee command not found!" -ForegroundColor Red
    Write-Host "Please run: . .\setup-environment.ps1" -ForegroundColor Yellow
    Write-Host "(Note the dot at the beginning to source the script)" -ForegroundColor Yellow
    exit 1
}

$startTime = Get-Date
$count = 0
$failures = 0
$failedRuns = @()

for ($i = 1; $i -le 200; $i++) {
    Write-Host "Run $i of 200..." -NoNewline
    
    $output = uv run --frozen pytest tests/client/test_stdio.py::test_stdio_context_manager_exiting -xvs -o addopts="" 2>&1
    $exitCode = $LASTEXITCODE
    
    if ($exitCode -ne 0) {
        $failures++
        $failedRuns += $i
        Write-Host " FAILED" -ForegroundColor Red
        Write-Host "Failure output:" -ForegroundColor Red
        Write-Host $output
        Write-Host ""
    } else {
        Write-Host " PASSED" -ForegroundColor Green
    }
}

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host ""
Write-Host "========== SUMMARY ==========" -ForegroundColor Cyan
Write-Host "Total runs: 200"
Write-Host "Successful runs: $(200 - $failures)" -ForegroundColor Green
Write-Host "Failed runs: $failures" -ForegroundColor Red
if ($failures -gt 0) {
    Write-Host "Failed on runs: $($failedRuns -join ', ')" -ForegroundColor Red
}
Write-Host "Duration: $($duration.ToString())"
Write-Host "Failure rate: $([math]::Round(($failures / 200) * 100, 2))%"