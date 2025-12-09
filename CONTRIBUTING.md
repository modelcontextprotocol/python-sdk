# Contributing

Thank you for your interest in contributing to the MCP Python SDK! This document provides guidelines and instructions for contributing.

## Before You Start

### Bug Fixes

Bug fixes are welcome! For straightforward bugs, feel free to open a PR directly. For complex bugs that require significant changes, consider opening an issue first to discuss the approach.

### New Features and Enhancements

**Please open an issue before starting work on new features or significant enhancements.** We will often close pull requests for new features that were not previously discussed. This isn't because we don't appreciate the contribution—it's because adding features creates long-term maintenance burden and requires alignment with the SDK's direction.

What counts as "significant"?

- New public APIs or decorators
- Architectural changes or refactoring
- Changes that touch multiple modules
- Features that might require spec changes (these need a [SEP](https://github.com/modelcontextprotocol/modelcontextprotocol) first)

### Good Candidates for Contribution

Issues labeled [`good first issue`](https://github.com/modelcontextprotocol/python-sdk/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22) or [`help wanted`](https://github.com/modelcontextprotocol/python-sdk/issues?q=is%3Aopen+is%3Aissue+label%3A%22help+wanted%22) are great places to start. Issues labeled [`ready for work`](https://github.com/modelcontextprotocol/python-sdk/issues?q=is%3Aopen+is%3Aissue+label%3A%22ready+for+work%22) have been triaged and are ready for implementation.

Issues labeled `needs confirmation` or `needs maintainer action` are **not** good candidates—please wait for maintainer input before starting work on these.

## Development Setup

1. Make sure you have Python 3.10+ installed
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
3. Fork the repository
4. Clone your fork: `git clone https://github.com/YOUR-USERNAME/python-sdk.git`
5. Install dependencies:

```bash
uv sync --frozen --all-extras --dev
```

6. Set up pre-commit hooks:

```bash
uv tool install pre-commit --with pre-commit-uv --force-reinstall
```

## Development Workflow

1. Choose the correct branch for your changes:
   - For bug fixes to a released version: use the latest release branch (e.g. v1.1.x for 1.1.3)
   - For new features: use the main branch (which will become the next minor/major version)
   - If unsure, ask in an issue first

2. Create a new branch from your chosen base branch

3. Make your changes

4. Ensure tests pass:

```bash
uv run pytest
```

5. Run type checking:

```bash
uv run pyright
```

6. Run linting:

```bash
uv run ruff check .
uv run ruff format .
```

7. Update README snippets if you modified example code:

```bash
uv run scripts/update_readme_snippets.py
```

8. (Optional) Run pre-commit hooks on all files:

```bash
pre-commit run --all-files
```

9. Submit a pull request to the same branch you branched from

## Code Style

- We use `ruff` for linting and formatting
- Follow PEP 8 style guidelines
- Add type hints to all functions
- Include docstrings for public APIs

## Pull Request Process

1. Update documentation as needed
2. Add tests for new functionality
3. Ensure CI passes
4. Maintainers will review your code
5. Address review feedback

## Code of Conduct

Please note that this project is released with a [Code of Conduct](CODE_OF_CONDUCT.md). By participating in this project you agree to abide by its terms.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
