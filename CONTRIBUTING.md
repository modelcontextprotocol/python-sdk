# Contributing

Thank you for your interest in contributing to the MCP Python SDK! This document provides guidelines and instructions for contributing.

## Before You Start

We welcome contributions! These guidelines exist to save everyone time, yours included. Following them means your work is more likely to be accepted.

**All pull requests require a corresponding issue.** Unless your change is trivial (typo, docs tweak, broken link), create an issue first. Every merged feature becomes ongoing maintenance, so we need to agree something is worth doing before reviewing code. PRs without a linked issue will be closed.

Having an issue doesn't guarantee acceptance. Wait for maintainer feedback or a `ready for work` label before starting. PRs for issues without buy-in may also be closed.

Use issues to validate your idea before investing time in code. PRs are for execution, not exploration.

### The SDK is Opinionated

Not every contribution will be accepted, even with a working implementation. We prioritize maintainability and consistency over adding capabilities. This is at maintainers' discretion.

### What Needs Discussion

These always require an issue first:

- New public APIs or decorators
- Architectural changes or refactoring
- Changes that touch multiple modules
- Features that might require spec changes (these need a [SEP](https://github.com/modelcontextprotocol/modelcontextprotocol) first)

Bug fixes for clear, reproducible issues are welcome—but still create an issue to track the fix.

### Finding Issues to Work On

| Label | For | Description |
|-------|-----|-------------|
| [`good first issue`](https://github.com/modelcontextprotocol/python-sdk/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22) | Newcomers | Can tackle without deep codebase knowledge |
| [`help wanted`](https://github.com/modelcontextprotocol/python-sdk/issues?q=is%3Aopen+is%3Aissue+label%3A%22help+wanted%22) | Experienced contributors | Maintainers probably won't get to this |
| [`ready for work`](https://github.com/modelcontextprotocol/python-sdk/issues?q=is%3Aopen+is%3Aissue+label%3A%22ready+for+work%22) | Maintainers | Triaged and ready for a maintainer to pick up |

Issues labeled `needs confirmation` or `needs maintainer action` are **not** ready for work—wait for maintainer input first.

Before starting, comment on the issue so we can assign it to you. This prevents duplicate effort.

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

   | Change Type | Target Branch | Example |
   |-------------|---------------|---------|
   | New features, breaking changes | `main` | New APIs, refactors |
   | Security fixes for v1 | `v1.x` | Critical patches |
   | Bug fixes for v1 | `v1.x` | Non-breaking fixes |

   > **Note:** `main` is the v2 development branch. Breaking changes are welcome on `main`. The `v1.x` branch receives only security and critical bug fixes.

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

## Pull Requests

By the time you open a PR, the "what" and "why" should already be settled in an issue. This keeps reviews focused on implementation.

### Scope

Small PRs get reviewed fast. Large PRs sit in the queue.

A few dozen lines can be reviewed in minutes. Hundreds of lines across many files takes real effort and things slip through. If your change is big, break it into smaller PRs or get alignment from a maintainer first.

### What Gets Rejected

- **No prior discussion**: Features or significant changes without an approved issue
- **Scope creep**: Changes that go beyond what was discussed
- **Misalignment**: Even well-implemented features may be rejected if they don't fit the SDK's direction
- **Overengineering**: Unnecessary complexity for simple problems

### Checklist

1. Update documentation as needed
2. Add tests for new functionality
3. Ensure CI passes
4. Address review feedback

## Code of Conduct

Please note that this project is released with a [Code of Conduct](CODE_OF_CONDUCT.md). By participating in this project you agree to abide by its terms.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
