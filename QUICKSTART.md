# MCP Python SDK - Quick Start

**Status**: ✅ **READY FOR DEVELOPMENT**

## Setup (2 minutes)

```bash
# 1. Install uv
pip install uv

# 2. Sync dependencies
uv sync

# 3. Verify setup
uv run --frozen ruff check .
PYTEST_DISABLE_PLUGIN_AUTOLOAD="" uv run --frozen pytest -x
```

## Daily Development

```bash
# Format code
uv run --frozen ruff format .

# Run tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD="" uv run --frozen pytest

# Type check
uv run --frozen pyright

# Build
uv build
```

## Project Resources

- **📖 Full Setup Guide**: `SETUP.md`
- **📊 Status Report**: `PROJECT_STATUS.md`
- **👥 Contributing**: `CONTRIBUTING.md`
- **💻 Development Rules**: `CLAUDE.md`
- **📚 Main Docs**: `README.md`

## Test Results

✅ 678 tests passing
✅ All linting checks pass
✅ Type checking passes
✅ Build successful

## Ready to Go!

The project is fully configured. See `SETUP.md` for detailed instructions.
