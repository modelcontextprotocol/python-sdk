#!/usr/bin/env bash
#
# Build the v2 documentation site for this checkout into `site/`: the
# English site at the root plus one machine-translated site per enabled
# language under `site/<code>/` (see i18n/languages.yml).
#
# Zensical runs no MkDocs plugins or hooks, so the English build is three
# steps: materialise the API reference pages and the concrete config, build
# the site strictly (plus the anchor, order-independence and cross-reference
# checks Zensical doesn't do itself), then generate llms.txt and the per-page
# markdown renditions. A language site is the lighter recipe against a staged
# docs tree (English pages overlaid with that language's translations and
# stamped with status banners): it carries no API reference of its own — its
# nav entry and its prose links into `api/` point at the English one — so it
# has no mkdocstrings pass and none of the API generation or render-order
# work. This script is the single owner of both recipes, dependency sync
# included — CI (shared.yml, docs-preview.yml) and scripts/build-docs.sh all
# call it. The toolchain detection in docs-preview.yml and build-docs.sh keys
# on this file's path and expects the site under site/.
#
# Environment:
#   DOCS_LANGUAGES=en-only   build only the English site (fast local loop)
#   DOCS_LANGUAGES=ja,ko     build only these language sites after English
#   DOCS_SITE_URL=<url>      the URL the built site is served from. Defaults
#                            to mkdocs.yml's site_url (production); a PR
#                            preview passes its own host so that every
#                            absolute link the build bakes — each site's
#                            site_url, the language switcher, the banners'
#                            English-page links, the language sites' links
#                            into the English API reference — resolves on the
#                            host the reader is actually browsing.
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
# (and the checks below) are deterministic. The staged language trees are
# rebuilt from scratch for the same reason.
rm -rf .cache site .build/i18n

# Fast, no-network gates before anything is generated or built: every prose
# heading carries an explicit anchor (so anchors survive translation and
# rewording), and the translation config plus the committed translations are
# structurally valid, so an invalid page can never reach a site.
uv run --frozen --no-sync python scripts/docs/check_anchors.py
uv run --frozen --no-sync python scripts/docs/i18n check

# The language sites this build produces: every enabled language, a chosen
# subset (DOCS_LANGUAGES=ja,ko), or none (DOCS_LANGUAGES=en-only). Decided once
# so the English config and every language config get the same switcher list,
# and the switcher can never link a site the build didn't make.
if [[ "${DOCS_LANGUAGES:-}" == "en-only" ]]; then
    languages=""
elif [[ -n "${DOCS_LANGUAGES:-}" ]]; then
    languages="${DOCS_LANGUAGES//,/ }"
else
    languages="$(uv run --frozen --no-sync python scripts/docs/i18n languages | tr '\n' ' ')"
fi
switcher="$(echo $languages | tr ' ' ',')"

# The URL the site is served from (see DOCS_SITE_URL above), decided once and
# handed to every config and to staging so all baked links agree on it.
site_url="${DOCS_SITE_URL:-}"
if [[ -z "$site_url" ]]; then
    site_url="$(uv run --frozen --no-sync python -c 'import yaml; print(yaml.safe_load(open("mkdocs.yml", encoding="utf-8"))["site_url"])')"
fi

uv run --frozen --no-sync python scripts/docs/build_config.py --site-url "$site_url" --switcher-languages "$switcher"

uv run --frozen --no-sync zensical build -f mkdocs.gen.yml --strict

# The build above renders pages in one arbitrary (filesystem-dependent)
# order; prove the API reference renders in hostile orders too — see the
# check's docstring for the failure mode this guards. Only the English site
# builds the API reference, so the property is checked only here.
uv run --frozen --no-sync python scripts/docs/check_render_order.py

# Zensical stays green even under --strict when a cross-reference fails to
# resolve (rendered as literal bracket text) or an objects.inv inventory
# fails to download (every link through it silently degrades to plain text);
# MkDocs strict mode aborted on both. Validate the built site instead.
uv run --frozen --no-sync python scripts/docs/check_crossrefs.py --site-dir site --config mkdocs.gen.yml

uv run --frozen --no-sync python scripts/docs/llms_txt.py --site-dir site

for lang in $languages; do
    echo "=== Building language site: ${lang} ==="
    # Stage the language's docs tree (English + translations + banners, API
    # links pointed at the English reference), generate its config, then
    # build it cold and check its cross-references.
    uv run --frozen --no-sync python scripts/docs/i18n stage --lang "$lang" --site-url "$site_url"
    uv run --frozen --no-sync python scripts/docs/build_config.py --lang "$lang" \
        --site-url "$site_url" --switcher-languages "$switcher"
    rm -rf .cache
    uv run --frozen --no-sync zensical build -f "mkdocs.${lang}.gen.yml" --strict
    uv run --frozen --no-sync python scripts/docs/check_crossrefs.py \
        --site-dir ".build/i18n/${lang}/site" --config "mkdocs.${lang}.gen.yml"
    mkdir -p "site/${lang}"
    cp -a ".build/i18n/${lang}/site/." "site/${lang}/"
done
