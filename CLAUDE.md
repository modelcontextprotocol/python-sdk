# Development Guidelines

This document contains critical information about working with this codebase. Follow these guidelines precisely.

## Core Development Rules

1. Package Management
   - ONLY use uv, NEVER pip
   - Installation: `uv add package`
   - Running tools: `uv run tool`
   - Upgrading: `uv add --dev package --upgrade-package package`
   - FORBIDDEN: `uv pip install`, `@latest` syntax

2. Code Quality
   - Type hints required for all code
   - Public APIs must have docstrings
   - Functions must be focused and small
   - Follow existing patterns exactly
   - Line length: 120 chars maximum

3. Testing Requirements
   - Framework: `uv run --frozen pytest`
   - Async testing: use anyio, not asyncio
   - Coverage: test edge cases and errors
   - New features require tests
   - Bug fixes require regression tests
   - Documentation
     - Test changes in docs/ and Python docstrings: `uv run mkdocs build`
     - On macOS: `export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib & uv run mkdocs build`
     - Fix WARNING and ERROR issues and re-run build until clean

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

- Always add `jerome3o-anthropic` and `jspahrsummers` as reviewer.

- NEVER ever mention a `co-authored-by` or similar aspects. In particular, never
  mention the tool used to create the commit message or PR.

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
     - Imports: split into multiple lines

2. Type Checking
   - Tool: `uv run --frozen pyright`
   - Requirements:
     - Explicit None checks for Optional
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
   - Pytest:
     - If the tests aren't finding the anyio pytest mark, try adding PYTEST_DISABLE_PLUGIN_AUTOLOAD=""
       to the start of the pytest run command eg:
       `PYTEST_DISABLE_PLUGIN_AUTOLOAD="" uv run --frozen pytest`

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
- **Only catch `Exception` for**:
  - Top-level handlers that must not crash
  - Cleanup blocks (log at debug level)

## Docstring best practices for SDK documentation

The following guidance ensures docstrings are genuinely helpful for new SDK users by providing navigation, context, and accurate examples.

### Structure and formatting

- Follow Google Python Style Guide for docstrings
- Format docstrings in Markdown compatible with mkdocs-material and mkdocstrings
- Always surround lists with blank lines (before and after) - also applies to Markdown (.md) files
- Always surround headings with blank lines - also applies to Markdown (.md) files
- Always surround fenced code blocks with blank lines - also applies to Markdown (.md) files
- Use sentence case for all headings and heading-like text - also applies to Markdown (.md) files

### Content requirements

- Access patterns: Explicitly state how users typically access the method/class with phrases like "You typically access this
method through..." or "You typically call this method by..."
- Cross-references: Use extensive cross-references to related members to help SDK users navigate:
  - Format: [`displayed_text`][module.path.to.Member]
  - Include backticks around the displayed text
  - Link to types, related methods, and alternative approaches
- Parameter descriptions:
  - Document all valid values for enums/literals
  - Explain what each parameter does and when to use it
  - Cross-reference parameter types where helpful
- Real-world examples:
  - Show actual usage patterns from the SDK, not theoretical code
  - Include imports and proper module paths
  - Verify examples against source code for accuracy
  - Show multiple approaches (e.g., low-level SDK vs FastMCP)
  - Add comments explaining what's happening
  - Examples should be concise and only as complex as needed to clearly demonstrate real-world usage
- Context and purpose:
  - Explain not just what the method does, but why and when to use it
  - Include notes about important considerations (e.g., client filtering, performance)
  - Mention alternative approaches where applicable

### Verification

  - All code examples MUST be 100% accurate to the actual SDK implementation
  - Verify imports, class names, method signatures against source code
  - You MUST NOT rely on existing documentation as authoritative - you MUST check the source
