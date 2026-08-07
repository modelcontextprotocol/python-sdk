#!/usr/bin/env bash
#
# Build the v2 documentation site for this checkout into `site/`: the English
# site at the root plus one machine-translated site per language listed in
# i18n/languages.yml, under `site/<code>/`.
#
# Zensical runs no MkDocs plugins or hooks, so the English build is three
# steps: materialise the API reference pages and the concrete config, build
# the site strictly (plus the order-independence and cross-reference checks
# Zensical doesn't do itself), then generate llms.txt and the per-page markdown
# renditions. A language site is the lighter recipe against the docs tree the
# translation tool stages (English pages with translations overlaid and status
# notices stamped in); it carries no API reference of its own — its nav entry and
# prose links point at the English one. This script is the single owner of the
# recipe, dependency sync included — CI (shared.yml, docs-preview.yml) and
# scripts/build-docs.sh all call it. The toolchain detection in
# docs-preview.yml and build-docs.sh keys on this file's path and expects the
# site under site/.
#
# Environment:
#   DOCS_LANGUAGES=en-only   build only the English site (fast local loop)
#   DOCS_LANGUAGES=ja,ko     build only these language sites after English
#   DOCS_SITE_URL=<url>      the URL the site is served from; defaults to
#                            mkdocs.yml's site_url. A PR preview passes its
#                            own host so every absolute link the build bakes
#                            (language switcher, banner links, links into the
#                            English API reference) resolves on the host the
#                            reader is browsing.
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
rm -rf .cache site .build/i18n

# The language sites this build produces (comma-separated), decided once so
# every site's switcher lists exactly the sites that exist.
languages="${DOCS_LANGUAGES-$(uv run --frozen --no-sync python scripts/docs/translations.py languages | paste -sd, -)}"
[[ "$languages" == "en-only" ]] && languages=""
site_url="${DOCS_SITE_URL:-}"

uv run --frozen --no-sync python scripts/docs/build_config.py --languages "$languages" ${site_url:+--site-url "$site_url"}
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

# The English site must already be in site/ before this loop: `zensical build`
# deletes anything foreign in its site_dir, so the English build (site_dir
# site/) would wipe every site/<code>/, while a language build (site_dir
# site/<code>/) leaves its siblings and parent alone.
for lang in ${languages//,/ }; do
    echo "=== Building language site: ${lang} ==="
    uv run --frozen --no-sync python scripts/docs/translations.py stage --lang "$lang" ${site_url:+--site-url "$site_url"}
    uv run --frozen --no-sync python scripts/docs/build_config.py --lang "$lang" --languages "$languages" \
        ${site_url:+--site-url "$site_url"}
    rm -rf .cache
    uv run --frozen --no-sync zensical build -f "mkdocs.${lang}.gen.yml" --strict
done
