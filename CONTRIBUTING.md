# Contributing

Thank you for your interest in contributing to the MCP Python SDK! This document provides guidelines and instructions for contributing.

## Development Setup

1. Make sure you have Python 3.10+ installed
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
3. Fork the repository
4. Clone your fork: `git clone https://github.com/YOUR-USERNAME/python-sdk.git`
5. Install dependencies:
```bash
uv sync --frozen --all-extras --dev
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

7. Submit a pull request to the same branch you branched from

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
