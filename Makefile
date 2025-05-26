# Development Makefile for modelcontextprotocol-python-sdk

# Variables
PYTHON := uv run
UV := uv

# Default target
.DEFAULT_GOAL := help

# Phony targets
.PHONY: help install sync test type-check lint-check lint-format lint clean all dev

# Help command
help:
	@echo "Available commands:"
	@echo "  make install      - Install dependencies with all extras and dev dependencies"
	@echo "  make sync         - Sync dependencies (frozen, all extras, dev)"
	@echo "  make test         - Run pytest tests"
	@echo "  make type-check   - Run pyright type checker"
	@echo "  make lint-check   - Run ruff linter checks"
	@echo "  make lint-format  - Run ruff formatter"
	@echo "  make lint         - Run both linter and formatter"
	@echo "  make clean        - Clean cache files"
	@echo "  make all          - Run all checks (test, type-check, lint)"
	@echo "  make dev          - Setup dev environment and run all checks"

# Install dependencies
install:
	$(UV) sync --all-extras --dev

# Sync dependencies (frozen)
sync:
	$(UV) sync --frozen --all-extras --dev

# Run tests
test: sync
	$(PYTHON) pytest

# Run type checking
type-check: sync
	$(PYTHON) pyright

# Run linter checks
lint-check: sync
	$(PYTHON) ruff check .

# Run formatter
lint-format: sync
	$(PYTHON) ruff format .

# Combined lint target
lint: lint-check lint-format

# Clean cache files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pyright" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Run all checks
all: test type-check lint

# Development setup and run all checks
dev: sync all
	@echo "✅ Development environment is ready and all checks passed!"

# Additional useful targets

# Watch tests (requires pytest-watch)
.PHONY: test-watch
test-watch: sync
	$(PYTHON) pytest-watch

# Run specific test file
.PHONY: test-file
test-file: sync
	@if [ -z "$(FILE)" ]; then \
		echo "Usage: make test-file FILE=path/to/test_file.py"; \
		exit 1; \
	fi
	$(PYTHON) pytest $(FILE)

# Coverage report
.PHONY: coverage
coverage: sync
	$(PYTHON) pytest --cov=. --cov-report=html --cov-report=term

# Format check only (no changes)
.PHONY: format-check
format-check: sync
	$(PYTHON) ruff format --check .

# Auto-fix linting issues
.PHONY: fix
fix: sync
	$(PYTHON) ruff check . --fix

# Quick check - faster than 'all' as it runs in parallel
.PHONY: check
check: sync
	@echo "Running all checks in parallel..."
	@$(MAKE) -j3 test type-check lint-check format-check
