#!/usr/bin/env bash
#
# Build combined v1 + v2 MkDocs documentation for GitHub Pages.
#
# v1 docs (from the v1.x branch) are placed at the site root.
# v2 docs (from main) are placed under /v2/.
#
# Both branches are fetched fresh from origin, so the output is identical
# regardless of which branch triggered the workflow. This script is intended
# to run in CI; for local single-branch preview use `uv run mkdocs serve`.
#
# Usage:
#   scripts/build-docs.sh [output-dir]
#
# Default output directory: site
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$(cd "$REPO_ROOT" && mkdir -p "${1:-site}" && cd "${1:-site}" && pwd)"
V1_WORKTREE="$REPO_ROOT/.worktrees/v1-docs"
V2_WORKTREE="$REPO_ROOT/.worktrees/v2-docs"

cleanup() {
    cd "$REPO_ROOT"
    git worktree remove --force "$V1_WORKTREE" 2>/dev/null || true
    git worktree remove --force "$V2_WORKTREE" 2>/dev/null || true
    rmdir "$REPO_ROOT/.worktrees" 2>/dev/null || true
}
trap cleanup EXIT

rm -rf "${OUTPUT_DIR:?}"/*

build_branch() {
    local branch="$1" worktree="$2" dest="$3"

    echo "=== Building docs for ${branch} ==="
    git fetch origin "$branch"
    git worktree remove --force "$worktree" 2>/dev/null || true
    rm -rf "$worktree"
    git worktree add --detach "$worktree" "origin/${branch}"

    (
        cd "$worktree"
        uv sync --frozen --group docs
        uv run --frozen --no-sync mkdocs build --site-dir "$dest"
    )
}

build_branch v1.x "$V1_WORKTREE" "$OUTPUT_DIR"
build_branch main "$V2_WORKTREE" "$OUTPUT_DIR/v2"

echo "=== Combined docs built at $OUTPUT_DIR ==="
