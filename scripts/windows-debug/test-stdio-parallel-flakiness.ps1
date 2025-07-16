#!/usr/bin/env pwsh
# Script to test for flakiness when running tests in parallel (like CI does)
# This simulates the xdist environment where the issue occurs
# Usage: .\test-stdio-parallel-flakiness.ps1
#
# Prerequisites: Run . .\setup-environment.ps1 first to ensure tee is available

Write-Host "Testing stdio with parallel execution to simulate CI environment..." -ForegroundColor Cyan
Write-Host ""

# Check if tee is available
$teeCheck = python -c "import shutil; print(shutil.which('tee'))"
if (-not $teeCheck -or $teeCheck -eq "None") {
    Write-Host "ERROR: tee command not found!" -ForegroundColor Red
    Write-Host "Please run: . .\setup-environment.ps1" -ForegroundColor Yellow
    Write-Host "(Note the dot at the beginning to source the script)" -ForegroundColor Yellow
    exit 1
}

Write-Host "Running tests with different parallel configurations..." -ForegroundColor Yellow
Write-Host ""

# Test 1: Run with 4 workers (default CI behavior)
Write-Host "Test 1: Running with 4 parallel workers (CI default)..." -ForegroundColor Cyan
$failures1 = 0
for ($i = 1; $i -le 20; $i++) {
    Write-Host "  Run $i..." -NoNewline
    $output = uv run --frozen pytest tests/client/test_stdio.py::test_stdio_context_manager_exiting -v -n 4 2>&1
    if ($LASTEXITCODE -ne 0) {
        $failures1++
        Write-Host " FAILED" -ForegroundColor Red
    } else {
        Write-Host " PASSED" -ForegroundColor Green
    }
}
Write-Host "  Result: $failures1 failures out of 20 runs" -ForegroundColor $(if ($failures1 -eq 0) { "Green" } else { "Red" })
Write-Host ""

# Test 2: Run with 2 workers
Write-Host "Test 2: Running with 2 parallel workers..." -ForegroundColor Cyan
$failures2 = 0
for ($i = 1; $i -le 20; $i++) {
    Write-Host "  Run $i..." -NoNewline
    $output = uv run --frozen pytest tests/client/test_stdio.py::test_stdio_context_manager_exiting -v -n 2 2>&1
    if ($LASTEXITCODE -ne 0) {
        $failures2++
        Write-Host " FAILED" -ForegroundColor Red
    } else {
        Write-Host " PASSED" -ForegroundColor Green
    }
}
Write-Host "  Result: $failures2 failures out of 20 runs" -ForegroundColor $(if ($failures2 -eq 0) { "Green" } else { "Red" })
Write-Host ""

# Test 3: Run all stdio tests in parallel (simulates real CI)
Write-Host "Test 3: Running ALL stdio tests with 4 workers (full CI simulation)..." -ForegroundColor Cyan
$failures3 = 0
for ($i = 1; $i -le 10; $i++) {
    Write-Host "  Run $i..." -NoNewline
    $output = uv run --frozen pytest tests/client/test_stdio.py -v -n 4 2>&1
    if ($LASTEXITCODE -ne 0) {
        $failures3++
        Write-Host " FAILED" -ForegroundColor Red
        # Show which test failed
        $failedTest = $output | Select-String "FAILED tests/client/test_stdio.py::" | Select-Object -First 1
        if ($failedTest) {
            Write-Host "    Failed: $failedTest" -ForegroundColor Red
        }
    } else {
        Write-Host " PASSED" -ForegroundColor Green
    }
}
Write-Host "  Result: $failures3 failures out of 10 runs" -ForegroundColor $(if ($failures3 -eq 0) { "Green" } else { "Red" })
Write-Host ""

# Summary
Write-Host "========== SUMMARY ==========" -ForegroundColor Cyan
Write-Host "4 workers (single test): $failures1/20 failures"
Write-Host "2 workers (single test): $failures2/20 failures"
Write-Host "4 workers (all tests):   $failures3/10 failures"
Write-Host ""

if ($failures1 -gt 0 -or $failures2 -gt 0 -or $failures3 -gt 0) {
    Write-Host "FLAKINESS DETECTED with parallel execution!" -ForegroundColor Red
    Write-Host ""
    Write-Host "This confirms the issue is related to parallel test execution." -ForegroundColor Yellow
    Write-Host "The race condition likely involves:" -ForegroundColor Yellow
    Write-Host "  - Windows Job Object handle management" -ForegroundColor Gray
    Write-Host "  - Process cleanup timing with multiple workers" -ForegroundColor Gray
    Write-Host "  - Handle inheritance between test processes" -ForegroundColor Gray
} else {
    Write-Host "No flakiness detected in this run." -ForegroundColor Green
    Write-Host "The issue might require specific timing conditions to reproduce." -ForegroundColor Yellow
}