#!/usr/bin/env bash
#
# Serve the v2 documentation locally with live reload.
#
# Regenerates the API reference and the concrete Zensical config, then serves
# it. Re-run the script to pick up changes to `src/` (the API reference) or the
# nav; edits to prose pages under `docs/` are picked up by live reload.
#
# Usage:
#   scripts/serve-docs.sh [-- <extra zensical serve args>]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

uv run --frozen python scripts/docs/build_config.py
exec uv run --frozen zensical serve -f mkdocs.gen.yml "$@"
