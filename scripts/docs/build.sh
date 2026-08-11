#!/usr/bin/env bash
#
# Build the v2 documentation site for this checkout into `site/`: the English
# site at the root, then one translated site per language in
# i18n/languages.yml under `site/<code>/`.
#
# Zensical runs no MkDocs plugins or hooks, so the English build is three
# steps: materialise the API reference pages and the concrete config, build
# the site strictly (plus the order-independence and cross-reference checks
# Zensical doesn't do itself), then generate llms.txt and the per-page
# markdown renditions. A language site is lighter: the translation tool stages
# a docs tree (English pages overlaid with that language's translations),
# build_config.py writes its config, and Zensical builds it (non-strict: a
# dead link or anchor in a translation is a warning, counted at the end)
# straight into site/<code>/ — no API reference (it links the English one),
# so no render-order or cross-reference checks. This script is the single
# owner of that recipe, dependency sync included — CI (shared.yml,
# docs-preview.yml) and scripts/build-docs.sh all call it. The toolchain
# detection in docs-preview.yml and build-docs.sh keys on this file's path and
# expects the site under site/.
#
# Usage:
#   scripts/docs/build.sh       (DOCS_LANGUAGES=en-only skips the language sites)
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
# (and the checks below) are deterministic. Staged language trees likewise.
rm -rf .cache site .build/i18n

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

# Language sites build after English: `zensical build` clears its site_dir, so
# the English build (site_dir site/) would wipe every site/<code>/, while a
# language build (site_dir site/<code>/) leaves its parent alone. All the
# language trees are staged in one pass, which reads the English pages once.
languages=""
if [[ "${DOCS_LANGUAGES:-}" != "en-only" ]]; then
    languages="$(PYTHONPATH=scripts/docs uv run --frozen --no-sync python -c \
        'import build_config; print(*(language.code for language in build_config.load_registry().languages))')"
    uv run --frozen --no-sync python scripts/docs/translations.py stage
fi

for lang in $languages; do
    echo "=== Building language site: ${lang} ==="
    uv run --frozen --no-sync python scripts/docs/build_config.py --lang "$lang"
    rm -rf .cache
    log=".build/i18n/${lang}/build.log"
    uv run --frozen --no-sync zensical build -f "mkdocs.${lang}.gen.yml" 2>&1 | tee "$log"
    # Zensical reports each dead link/anchor as a "Warning:" diagnostic on stderr.
    echo "${lang}: $(grep -c 'Warning:' "$log" || true) warnings"
done
