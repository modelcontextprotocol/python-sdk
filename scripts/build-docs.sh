#!/usr/bin/env bash
#
# Build combined v1 + v2 documentation for GitHub Pages.
#
# The current major (v2, from main) is placed at the site root and mirrored
# under /v2/; the v1 maintenance line (from the v1.x branch) is placed under
# /v1/. Per-major paths are permanent: /v2/ is a byte-identical copy of the
# root so that /v2/... links keep resolving after a future major takes the
# root, the way /v1/... does for v1 today.
#
# The two lines use different toolchains: v1.x still builds with MkDocs, while
# main builds with Zensical (which needs a pre-build step to materialise the API
# reference and a post-build step for llms.txt — see scripts/docs/). Each branch
# is fetched fresh from origin and built with its own synced `docs` group. Only
# main deploys the combined site (the v1.x branch carries no deploy workflow), so
# a v1.x docs change goes live on the next main deploy or a manual
# `workflow_dispatch` of deploy-docs.yml. This script is intended to run in CI;
# for a local v2 preview use `scripts/serve-docs.sh`.
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
        uv sync --frozen --group docs
        NO_MKDOCS_2_WARNING=1 uv run --frozen --no-sync mkdocs build --site-dir site
    fi
}

# Fetch a branch fresh from origin, build its docs, and copy the result to
# `dest`. The built tree stays in `worktree/site` afterwards so a caller can
# mirror it to a second destination.
build_branch() {
    local branch="$1" worktree="$2" dest="$3"

    echo "=== Building docs for ${branch} ==="
    git fetch origin "$branch"
    git worktree remove --force "$worktree" 2>/dev/null || true
    rm -rf "$worktree"
    git worktree add --detach "$worktree" "origin/${branch}"

    (
        cd "$worktree"
        rm -rf site
        build_site
        mkdir -p "$dest"
        cp -a site/. "$dest/"
    )
}

rm -rf "${OUTPUT_DIR:?}"/*

# v2 (main) at the root, then mirrored to /v2/ from the same build, then v1
# under /v1/. The mirror is copied from the worktree's build directory rather
# than from the root so it never picks up the /v1/ tree.
build_branch main "$V2_WORKTREE" "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/v2"
cp -a "$V2_WORKTREE/site/." "$OUTPUT_DIR/v2/"
build_branch v1.x "$V1_WORKTREE" "$OUTPUT_DIR/v1"

echo "=== Combined docs built at $OUTPUT_DIR ==="
