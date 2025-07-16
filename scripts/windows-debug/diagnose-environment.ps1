#!/usr/bin/env pwsh
# Script to diagnose environment differences that might cause CI flakiness
# Usage: .\diagnose-environment.ps1

Write-Host "Diagnosing Windows environment for stdio test issues..." -ForegroundColor Cyan
Write-Host ""

# System Information
Write-Host "=== SYSTEM INFORMATION ===" -ForegroundColor Yellow
Write-Host "Windows Version:"
(Get-CimInstance Win32_OperatingSystem).Version
Write-Host "Windows Build:"
(Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion").DisplayVersion
Write-Host ""

# Python Information
Write-Host "=== PYTHON INFORMATION ===" -ForegroundColor Yellow
Write-Host "Python Version:"
python --version
Write-Host ""
Write-Host "Python Build Info:"
python -c "import sys; print(f'Version: {sys.version}')"
python -c "import sys; print(f'Platform: {sys.platform}')"
python -c "import sys; print(f'Windows Version: {sys.getwindowsversion()}')"
Write-Host ""

# Check subprocess configuration
Write-Host "=== SUBPROCESS CONFIGURATION ===" -ForegroundColor Yellow
python -c @"
import subprocess
import sys
print(f'CREATE_NO_WINDOW available: {hasattr(subprocess, "CREATE_NO_WINDOW")}')
print(f'CREATE_NEW_PROCESS_GROUP available: {hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP")}')
print(f'Windows subprocess startup info: {hasattr(subprocess, "STARTUPINFO")}')

# Check handle inheritance defaults
import os
print(f'\nHandle inheritance (os.O_NOINHERIT): {hasattr(os, "O_NOINHERIT")}')

# Check asyncio event loop
import asyncio
try:
    loop = asyncio.get_event_loop_policy()
    print(f'Event loop policy: {type(loop).__name__}')
except:
    print('Event loop policy: Unable to determine')
"@
Write-Host ""

# Check for Job Objects support
Write-Host "=== JOB OBJECTS SUPPORT ===" -ForegroundColor Yellow
python -c @"
try:
    import win32job
    import win32api
    print('pywin32 available: Yes')
    print(f'win32job version: {win32job.__file__}')
    
    # Try to create a job object
    try:
        job = win32job.CreateJobObject(None, '')
        win32api.CloseHandle(job)
        print('Job Object creation: Success')
    except Exception as e:
        print(f'Job Object creation: Failed - {e}')
except ImportError:
    print('pywin32 available: No (Job Objects not available)')
"@
Write-Host ""

# Check process limits
Write-Host "=== PROCESS LIMITS ===" -ForegroundColor Yellow
python -c @"
import os
import psutil
proc = psutil.Process(os.getpid())
print(f'Open handles: {proc.num_handles()}')
print(f'Open files: {len(proc.open_files())}')

# Check system-wide limits
print(f'Total processes: {len(psutil.pids())}')
"@
Write-Host ""

# Check security software
Write-Host "=== SECURITY SOFTWARE ===" -ForegroundColor Yellow
Get-CimInstance -Namespace "root\SecurityCenter2" -ClassName AntiVirusProduct -ErrorAction SilentlyContinue | 
    Select-Object displayName, productState | Format-Table
Write-Host ""

# Test rapid process creation
Write-Host "=== RAPID PROCESS CREATION TEST ===" -ForegroundColor Yellow
Write-Host "Testing rapid tee process creation/destruction..."
$testScript = @'
import time
import subprocess
import sys

failures = 0
times = []

for i in range(20):
    start = time.time()
    try:
        # Create process with same flags as stdio client
        proc = subprocess.Popen(
            ['tee'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        proc.stdin.close()
        proc.wait(timeout=0.5)
        elapsed = time.time() - start
        times.append(elapsed)
    except Exception as e:
        failures += 1
        print(f"  Iteration {i+1}: FAILED - {e}")
    
    if (i+1) % 5 == 0:
        avg_time = sum(times) / len(times) if times else 0
        print(f"  Completed {i+1}/20 (avg: {avg_time*1000:.1f}ms)")

print(f"\nFailures: {failures}/20")
if times:
    print(f"Average time: {sum(times)/len(times)*1000:.1f}ms")
    print(f"Max time: {max(times)*1000:.1f}ms")
'@

python -c $testScript
Write-Host ""

# Environment variables that might affect subprocess
Write-Host "=== RELEVANT ENVIRONMENT VARIABLES ===" -ForegroundColor Yellow
@("COMSPEC", "PATH", "PYTHONPATH", "PYTHONASYNCIODEBUG") | ForEach-Object {
    $value = [Environment]::GetEnvironmentVariable($_)
    if ($value) {
        Write-Host "$_`:"
        Write-Host "  $value" -ForegroundColor Gray
    }
}
Write-Host ""

Write-Host "=== DIAGNOSIS COMPLETE ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Share this output when reporting the flakiness issue." -ForegroundColor Yellow
Write-Host "Key differences to look for between local and CI:" -ForegroundColor Yellow
Write-Host "  - Windows version/build" -ForegroundColor Gray
Write-Host "  - Python build details" -ForegroundColor Gray
Write-Host "  - Security software presence" -ForegroundColor Gray
Write-Host "  - Process creation timing" -ForegroundColor Gray