#!/usr/bin/env bash
#
# Build the v2 documentation site for this checkout into `site/`.
#
# Zensical runs no MkDocs plugins or hooks, so the build is three steps:
# materialise the API reference pages and the concrete config, build the
# site strictly (plus the order-independence and cross-reference checks
# Zensical doesn't do itself), then generate llms.txt and the per-page
# markdown renditions. This script is the single owner of that recipe, dependency
# sync included — CI (shared.yml, docs-preview.yml) and scripts/build-docs.sh
# all call it. The toolchain detection in docs-preview.yml and build-docs.sh
# keys on this file's path and expects the site under site/.
#
# Usage:
#   scripts/docs/build.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Snippet includes (`--8<--`) resolve against the working directory, which
# must therefore be the repo root.
cd "$SCRIPT_DIR/../.."

uv sync --frozen --group docs

# Zensical's incremental cache is unsound: a warm rebuild where only some
# pages re-render silently drops cross-references to cache-hit pages, and
# HTML for since-deleted pages lingers in site/. Build cold so the output
# (and the checks below) are deterministic.
rm -rf .cache site

uv run --frozen --no-sync python scripts/docs/build_config.py
uv run --frozen --no-sync zensical build -f mkdocs.gen.yml --strict

# The build above renders pages in one arbitrary (filesystem-dependent)
# order; prove the API reference renders in hostile orders too — see the
# check's docstring for the failure mode this guards.
uv run --frozen --no-sync python scripts/docs/check_render_order.py

# Zensical stays green even under --strict when a cross-reference fails to
# resolve (rendered as literal bracket text) or an objects.inv inventory
# fails to download (every link through it silently degrades to plain text);
# MkDocs strict mode aborted on both. Validate the built site instead.
uv run --frozen --no-sync python scripts/docs/check_crossrefs.py --site-dir site

uv run --frozen --no-sync python scripts/docs/llms_txt.py --site-dir site
