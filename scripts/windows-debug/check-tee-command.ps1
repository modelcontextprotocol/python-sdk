#!/usr/bin/env pwsh
# Script to check if tee command is available on Windows
# Usage: .\check-tee-command.ps1

Write-Host "Checking for 'tee' command availability on Windows..." -ForegroundColor Cyan
Write-Host ""

# Store original PATH
$originalPath = $env:PATH

# Method 1: Using where.exe
Write-Host "Method 1: Using where.exe" -ForegroundColor Yellow
try {
    $whereResult = where.exe tee 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Found tee at: $whereResult" -ForegroundColor Green
    } else {
        Write-Host "  tee not found via where.exe" -ForegroundColor Red
    }
} catch {
    Write-Host "  Error checking with where.exe: $_" -ForegroundColor Red
}

Write-Host ""

# Method 2: Using Get-Command
Write-Host "Method 2: Using Get-Command" -ForegroundColor Yellow
try {
    $getCommandResult = Get-Command tee -ErrorAction Stop
    Write-Host "  Found tee:" -ForegroundColor Green
    Write-Host "    Name: $($getCommandResult.Name)"
    Write-Host "    CommandType: $($getCommandResult.CommandType)"
    Write-Host "    Source: $($getCommandResult.Source)"
    Write-Host "    Version: $($getCommandResult.Version)"
} catch {
    Write-Host "  tee not found via Get-Command" -ForegroundColor Red
}

Write-Host ""

# Method 3: Check common locations
Write-Host "Method 3: Checking common locations" -ForegroundColor Yellow
$commonPaths = @(
    "C:\Program Files\Git\usr\bin\tee.exe",
    "C:\Program Files (x86)\Git\usr\bin\tee.exe",
    "C:\tools\msys64\usr\bin\tee.exe",
    "C:\msys64\usr\bin\tee.exe",
    "C:\cygwin64\bin\tee.exe",
    "C:\cygwin\bin\tee.exe"
)

$found = $false
foreach ($path in $commonPaths) {
    if (Test-Path $path) {
        Write-Host "  Found at: $path" -ForegroundColor Green
        $found = $true
    }
}

if (-not $found) {
    Write-Host "  tee not found in common locations" -ForegroundColor Red
}

Write-Host ""

# Method 4: Check if it's a PowerShell alias
Write-Host "Method 4: Checking PowerShell aliases" -ForegroundColor Yellow
$alias = Get-Alias tee -ErrorAction SilentlyContinue
if ($alias) {
    Write-Host "  Found PowerShell alias:" -ForegroundColor Green
    Write-Host "    Name: $($alias.Name)"
    Write-Host "    Definition: $($alias.Definition)"
} else {
    Write-Host "  No PowerShell alias for tee" -ForegroundColor Yellow
}

Write-Host ""

# Method 5: Python check (what the test uses)
Write-Host "Method 5: Python shutil.which() check" -ForegroundColor Yellow
$pythonCheck = python -c "import shutil; print(shutil.which('tee'))"
if ($pythonCheck -and $pythonCheck -ne "None") {
    Write-Host "  Python found tee at: $pythonCheck" -ForegroundColor Green
} else {
    Write-Host "  Python shutil.which() did not find tee" -ForegroundColor Red
}

Write-Host ""

# Method 6: Try adding Git for Windows to PATH if it exists
Write-Host "Method 6: Adding Git for Windows to PATH temporarily" -ForegroundColor Yellow
$gitPaths = @(
    "C:\Program Files\Git\usr\bin",
    "C:\Program Files (x86)\Git\usr\bin"
)

$addedToPath = $false
foreach ($gitPath in $gitPaths) {
    if (Test-Path $gitPath) {
        Write-Host "  Found Git directory: $gitPath" -ForegroundColor Green
        $env:PATH = "$gitPath;$env:PATH"
        $teeCheck = python -c "import shutil; print(shutil.which('tee'))"
        if ($teeCheck -and $teeCheck -ne "None") {
            Write-Host "  tee is now available at: $teeCheck" -ForegroundColor Green
            $addedToPath = $true
            break
        }
    }
}

if (-not $addedToPath) {
    # Restore original PATH if we didn't find tee
    $env:PATH = $originalPath
    Write-Host "  Could not add Git for Windows tee to PATH" -ForegroundColor Red
}

Write-Host ""
Write-Host "========== SUMMARY ==========" -ForegroundColor Cyan
if ($whereResult -or $getCommandResult -or $found -or ($pythonCheck -and $pythonCheck -ne "None") -or $addedToPath) {
    Write-Host "tee command is available" -ForegroundColor Green
    Write-Host ""
    Write-Host "The test_stdio_context_manager_exiting test should run." -ForegroundColor Green
    if ($addedToPath) {
        Write-Host ""
        Write-Host "Note: Git for Windows tee was added to PATH for this session." -ForegroundColor Yellow
        Write-Host "To make this permanent, add this to your PowerShell profile:" -ForegroundColor Yellow
        Write-Host "  `$env:PATH = `"C:\Program Files\Git\usr\bin;`$env:PATH`"" -ForegroundColor Cyan
    }
} else {
    Write-Host "tee command is NOT available" -ForegroundColor Red
    Write-Host ""
    Write-Host "The test_stdio_context_manager_exiting test will be SKIPPED." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "To install tee on Windows, you can:" -ForegroundColor Cyan
    Write-Host "  1. Install Git for Windows (includes tee in Git Bash)"
    Write-Host "  2. Install WSL (Windows Subsystem for Linux)"
    Write-Host "  3. Install MSYS2 or Cygwin"
    Write-Host "  4. Use PowerShell's Tee-Object cmdlet (different syntax)"
}

# Restore original PATH
$env:PATH = $originalPath