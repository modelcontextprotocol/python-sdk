#!/usr/bin/env bash
#
# Build combined v1 + v2 documentation for GitHub Pages.
#
# v1 docs (from the v1.x branch) are placed at the site root.
# v2 docs (from main) are placed under /v2/.
#
# The two lines use different toolchains: v1.x still builds with MkDocs, while
# main builds with Zensical (which needs a pre-build step to materialise the API
# reference and a post-build step for llms.txt — see scripts/docs/). Each branch
# is fetched fresh from origin and built with its own synced `docs` group, so
# the output is identical regardless of which branch triggered the workflow.
# This script is intended to run in CI; for a local v2 preview use
# `scripts/serve-docs.sh`.
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

# Build the checked-out worktree into its local `site/`, picking the toolchain
# from the branch's own files rather than hard-coding it here: a branch that
# ships the Zensical build recipe (scripts/docs/build.sh) builds with it,
# otherwise it falls back to MkDocs. This keeps the combined build correct
# regardless of which branch triggered it. Zensical requires site_dir to live
# within the project root, so both paths build to the local `site/` and let
# the caller copy it to its destination.
build_site() {
    if [[ -f scripts/docs/build.sh ]]; then
        bash scripts/docs/build.sh
    else
        NO_MKDOCS_2_WARNING=1 uv run --frozen --no-sync mkdocs build --site-dir site
    fi
}

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
        rm -rf site
        build_site
        mkdir -p "$dest"
        cp -a site/. "$dest/"
    )
}

rm -rf "${OUTPUT_DIR:?}"/*

build_branch v1.x "$V1_WORKTREE" "$OUTPUT_DIR"
build_branch main "$V2_WORKTREE" "$OUTPUT_DIR/v2"

echo "=== Combined docs built at $OUTPUT_DIR ==="
