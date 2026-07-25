#!/usr/bin/env bash
#
# Build the v1.x documentation into ./site.
#
# This is the single build recipe for this branch's docs. The combined site
# is assembled and deployed from main, which fetches this branch and runs this
# script to build it under /v1/ (main's scripts/build-docs.sh picks
# scripts/docs/build.sh from each branch it builds). The `docs` CI job on
# this branch runs the same script, so what CI checks is what gets published.
#
# Usage:
#   scripts/docs/build.sh
#
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

uv sync --frozen --group docs
NO_MKDOCS_2_WARNING=1 uv run --frozen --no-sync mkdocs build --site-dir site
