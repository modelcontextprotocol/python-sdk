# Windows Test Debugging Scripts

This folder contains PowerShell scripts to help debug the flaky `test_stdio_context_manager_exiting` test on Windows with Python 3.11/3.12.

## Prerequisites

- Windows PowerShell or PowerShell Core
- Python 3.11 or 3.12
- `uv` installed and configured
- Virtual environment activated
- Git for Windows installed (provides the `tee` command)

## Quick Start

1. First, set up your environment to make `tee` available:
   ```powershell
   . .\setup-environment.ps1
   ```
   **Note:** The dot (.) at the beginning is important - it sources the script.

2. Verify the test runs:
   ```powershell
   .\test-stdio-simple.ps1
   ```

3. Run the flakiness tests:
   ```powershell
   .\test-stdio-flakiness-200-runs.ps1
   ```

## Scripts

### 1. `setup-environment.ps1`
Sets up the environment by adding Git for Windows tools to PATH. **Must be dot-sourced.**

```powershell
. .\setup-environment.ps1
```

### 2. `check-tee-command.ps1`
Checks if the `tee` command is available on your Windows system. The test requires `tee` to run.

```powershell
.\check-tee-command.ps1
```

### 3. `test-stdio-simple.ps1`
Runs the test once to verify it works.

```powershell
.\test-stdio-simple.ps1
```

### 4. `test-stdio-flakiness-200-runs.ps1`
Runs the test 200 times and reports the failure rate.

```powershell
.\test-stdio-flakiness-200-runs.ps1
```

### 5. `test-stdio-flakiness-until-failure.ps1`
Runs the test in a loop until it fails, useful for catching intermittent failures.

```powershell
.\test-stdio-flakiness-until-failure.ps1
```

### 6. `test-stdio-verbose-debug.ps1`
Runs the test once with maximum debugging output enabled.

```powershell
.\test-stdio-verbose-debug.ps1
```

## Usage Notes

1. Make sure your virtual environment is activated before running these scripts
2. Always run `setup-environment.ps1` first in each new PowerShell session
3. Run scripts from the `scripts\windows-debug` directory
4. If scripts fail with execution policy errors, run:
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

## Interpreting Results

- If `tee` is not available, the test will be skipped
- Flaky failures typically show up as timeout errors or process cleanup issues
- Look for patterns in failure output, especially around process termination timing

## Troubleshooting

### "tee command not found"
1. Install Git for Windows from https://gitforwindows.org/
2. Run `. .\setup-environment.ps1` to add Git tools to PATH
3. Verify with `python -c "import shutil; print(shutil.which('tee'))"`

### "no tests ran" with xdist
The scripts now use `-o addopts=""` to override the pytest configuration that enables xdist by default.

### Making PATH changes permanent
Add this line to your PowerShell profile:
```powershell
$env:PATH = "C:\Program Files\Git\usr\bin;$env:PATH"
```