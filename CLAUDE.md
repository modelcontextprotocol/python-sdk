# Development Guidelines

This document contains critical information about working with this codebase. Follow these guidelines precisely.

## Core Development Rules

1. Package Management
   - ONLY use uv, NEVER pip
   - Installation: `uv add <package>`
   - Running tools: `uv run <tool>`
   - Upgrading: `uv lock --upgrade-package <package>`
   - FORBIDDEN: `uv pip install`, `@latest` syntax

2. Code Quality
   - Type hints required for all code
   - Public APIs must have docstrings
   - Functions must be focused and small
   - Follow existing patterns exactly
   - Line length: 120 chars maximum
   - FORBIDDEN: imports inside functions. THEY SHOULD BE AT THE TOP OF THE FILE.

3. Testing Requirements
   - Framework: `uv run --frozen pytest`
   - Async testing: use anyio, not asyncio
   - Do not use `Test` prefixed classes, use functions
   - Coverage: test edge cases and errors
   - New features require tests
   - Bug fixes require regression tests
   - IMPORTANT: The `tests/client/test_client.py` is the most well designed test file. Follow its patterns.
   - IMPORTANT: Be minimal, and focus on E2E tests: Use the `mcp.client.Client` whenever possible.

- For commits fixing bugs or adding features based on user reports add:

  ```bash
  git commit --trailer "Reported-by:<name>"
  ```

  Where `<name>` is the name of the user.

- For commits related to a Github issue, add

  ```bash
  git commit --trailer "Github-Issue:#<number>"
  ```

- NEVER ever mention a `co-authored-by` or similar aspects. In particular, never
  mention the tool used to create the commit message or PR.

## Pull Requests

- Create a detailed message of what changed. Focus on the high level description of
  the problem it tries to solve, and how it is solved. Don't go into the specifics of the
  code unless it adds clarity.

- NEVER ever mention a `co-authored-by` or similar aspects. In particular, never
  mention the tool used to create the commit message or PR.

## Breaking Changes

When making breaking changes, document them in `docs/migration.md`. Include:

- What changed
- Why it changed
- How to migrate existing code

Search for related sections in the migration guide and group related changes together
rather than adding new standalone sections.

## Python Tools

## Code Formatting

1. Ruff
   - Format: `uv run --frozen ruff format .`
   - Check: `uv run --frozen ruff check .`
   - Fix: `uv run --frozen ruff check . --fix`
   - Critical issues:
     - Line length (88 chars)
     - Import sorting (I001)
     - Unused imports
   - Line wrapping:
     - Strings: use parentheses
     - Function calls: multi-line with proper indent
     - Imports: try to use a single line

2. Type Checking
   - Tool: `uv run --frozen pyright`
   - Requirements:
     - Type narrowing for strings
     - Version warnings can be ignored if checks pass

3. Pre-commit
   - Config: `.pre-commit-config.yaml`
   - Runs: on git commit
   - Tools: Prettier (YAML/JSON), Ruff (Python)
   - Ruff updates:
     - Check PyPI versions
     - Update config rev
     - Commit config first

## Error Resolution

1. CI Failures
   - Fix order:
     1. Formatting
     2. Type errors
     3. Linting
   - Type errors:
     - Get full line context
     - Check Optional types
     - Add type narrowing
     - Verify function signatures

2. Common Issues
   - Line length:
     - Break strings with parentheses
     - Multi-line function calls
     - Split imports
   - Types:
     - Add None checks
     - Narrow string types
     - Match existing patterns

3. Best Practices
   - Check git status before commits
   - Run formatters before type checks
   - Keep changes minimal
   - Follow existing patterns
   - Document public APIs
   - Test thoroughly

## Exception Handling

- **Always use `logger.exception()` instead of `logger.error()` when catching exceptions**
  - Don't include the exception in the message: `logger.exception("Failed")` not `logger.exception(f"Failed: {e}")`
- **Catch specific exceptions** where possible:
  - File ops: `except (OSError, PermissionError):`
  - JSON: `except json.JSONDecodeError:`
  - Network: `except (ConnectionError, TimeoutError):`
- **FORBIDDEN** `except Exception:` - unless in top-level handlers
