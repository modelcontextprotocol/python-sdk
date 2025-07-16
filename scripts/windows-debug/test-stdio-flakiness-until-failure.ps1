#!/usr/bin/env pwsh
# Script to run test_stdio_context_manager_exiting until it fails
# Usage: .\test-stdio-flakiness-until-failure.ps1

Write-Host "Running test_stdio_context_manager_exiting until failure..." -ForegroundColor Cyan
Write-Host "Test: tests/client/test_stdio.py::test_stdio_context_manager_exiting" -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

$startTime = Get-Date
$i = 0

while ($true) {
    $i++
    Write-Host "Run $i..." -NoNewline
    
    $output = uv run --frozen pytest tests/client/test_stdio.py::test_stdio_context_manager_exiting -xvs -n 0 2>&1
    $exitCode = $LASTEXITCODE
    
    if ($exitCode -ne 0) {
        $endTime = Get-Date
        $duration = $endTime - $startTime
        
        Write-Host " FAILED!" -ForegroundColor Red
        Write-Host ""
        Write-Host "========== FAILURE DETECTED ==========" -ForegroundColor Red
        Write-Host "Failed on run: $i" -ForegroundColor Red
        Write-Host "Time until failure: $($duration.ToString())" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Failure output:" -ForegroundColor Red
        Write-Host $output
        break
    } else {
        Write-Host " PASSED" -ForegroundColor Green
    }
    
    # Small delay to prevent overwhelming the system
    Start-Sleep -Milliseconds 100
}

Write-Host ""
Write-Host "Exiting after failure detection." -ForegroundColor Cyan