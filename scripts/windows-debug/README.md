# Windows Test Debugging Scripts

This folder contains PowerShell scripts to help debug the flaky `test_stdio_context_manager_exiting` test on Windows with Python 3.11/3.12.

## Prerequisites

- Windows PowerShell or PowerShell Core
- Python 3.11 or 3.12
- `uv` installed and configured
- Virtual environment activated

## Scripts

### 1. `check-tee-command.ps1`
Checks if the `tee` command is available on your Windows system. The test requires `tee` to run.

```powershell
.\check-tee-command.ps1
```

### 2. `test-stdio-flakiness-200-runs.ps1`
Runs the test 200 times and reports the failure rate.

```powershell
.\test-stdio-flakiness-200-runs.ps1
```

### 3. `test-stdio-flakiness-until-failure.ps1`
Runs the test in a loop until it fails, useful for catching intermittent failures.

```powershell
.\test-stdio-flakiness-until-failure.ps1
```

### 4. `test-stdio-verbose-debug.ps1`
Runs the test once with maximum debugging output enabled.

```powershell
.\test-stdio-verbose-debug.ps1
```

## Usage Notes

1. Make sure your virtual environment is activated before running these scripts
2. Run scripts from the repository root directory
3. If scripts fail with execution policy errors, run:
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

## Interpreting Results

- If `tee` is not available, the test will be skipped
- Flaky failures typically show up as timeout errors or process cleanup issues
- Look for patterns in failure output, especially around process termination timing