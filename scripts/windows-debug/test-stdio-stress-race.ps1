#!/usr/bin/env pwsh
# Script to stress test the specific race condition in stdio cleanup
# This creates many processes rapidly to expose handle/job object races
# Usage: .\test-stdio-stress-race.ps1
#
# Prerequisites: Run . .\setup-environment.ps1 first to ensure tee is available

Write-Host "Stress testing stdio cleanup race conditions..." -ForegroundColor Cyan
Write-Host "This test creates many processes rapidly to expose timing issues." -ForegroundColor Yellow
Write-Host ""

# Check if tee is available
$teeCheck = python -c "import shutil; print(shutil.which('tee'))"
if (-not $teeCheck -or $teeCheck -eq "None") {
    Write-Host "ERROR: tee command not found!" -ForegroundColor Red
    Write-Host "Please run: . .\setup-environment.ps1" -ForegroundColor Yellow
    Write-Host "(Note the dot at the beginning to source the script)" -ForegroundColor Yellow
    exit 1
}

# Create a Python script that runs the test many times in quick succession
$stressScript = @'
import asyncio
import sys
import time
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mcp.client.stdio import stdio_client, StdioServerParameters

async def rapid_test(test_id: int):
    """Run a single test iteration"""
    try:
        async with stdio_client(StdioServerParameters(command="tee")) as (_, _):
            pass
        return True, None
    except Exception as e:
        return False, str(e)

async def stress_test(iterations: int, concurrent: int):
    """Run many tests concurrently"""
    print(f"Running {iterations} tests with {concurrent} concurrent...")
    
    failures = 0
    errors = []
    start_time = time.time()
    
    # Run in batches
    for batch in range(0, iterations, concurrent):
        batch_size = min(concurrent, iterations - batch)
        tasks = [rapid_test(batch + i) for i in range(batch_size)]
        results = await asyncio.gather(*tasks)
        
        for success, error in results:
            if not success:
                failures += 1
                if error and error not in errors:
                    errors.append(error)
        
        # Progress indicator
        if (batch + batch_size) % 100 == 0:
            print(f"  Completed {batch + batch_size}/{iterations} tests...")
    
    duration = time.time() - start_time
    return failures, errors, duration

async def main():
    # Test different concurrency levels
    configs = [
        (100, 1),    # Sequential
        (100, 2),    # Low concurrency
        (100, 5),    # Medium concurrency
        (100, 10),   # High concurrency
    ]
    
    for iterations, concurrent in configs:
        print(f"\nTest: {iterations} iterations, {concurrent} concurrent")
        failures, errors, duration = await stress_test(iterations, concurrent)
        
        print(f"  Duration: {duration:.2f}s")
        print(f"  Failures: {failures}/{iterations}")
        if errors:
            print(f"  Unique errors: {len(errors)}")
            for error in errors[:3]:  # Show first 3 errors
                print(f"    - {error}")
        
        if failures > 0:
            print("  RACE CONDITION DETECTED!" if concurrent > 1 else "  FAILURE DETECTED!")

if __name__ == "__main__":
    asyncio.run(main())
'@

# Save the stress test script
$scriptPath = Join-Path $PSScriptRoot "stress_test.py"
$stressScript | Out-File -FilePath $scriptPath -Encoding UTF8

Write-Host "Running stress tests..." -ForegroundColor Cyan
Write-Host ""

# Run the stress test
uv run python $scriptPath

$exitCode = $LASTEXITCODE

# Clean up
Remove-Item $scriptPath -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "========== ANALYSIS ==========" -ForegroundColor Cyan

if ($exitCode -ne 0) {
    Write-Host "Stress test failed to complete." -ForegroundColor Red
} else {
    Write-Host "Stress test completed." -ForegroundColor Green
    Write-Host ""
    Write-Host "If failures increased with concurrency, it indicates:" -ForegroundColor Yellow
    Write-Host "  - Race condition in process cleanup" -ForegroundColor Gray
    Write-Host "  - Job Object handle conflicts" -ForegroundColor Gray
    Write-Host "  - Windows handle inheritance issues" -ForegroundColor Gray
    Write-Host ""
    Write-Host "This matches the CI flakiness pattern where parallel tests fail." -ForegroundColor Yellow
}