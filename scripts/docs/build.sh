#!/usr/bin/env bash
#
# Build the v2 documentation site for this checkout into `site/`.
#
# Zensical runs no MkDocs plugins or hooks, so the build is three steps:
# materialise the API reference pages and the concrete config, build the
# site strictly, then generate llms.txt and the per-page markdown
# renditions. This script is the single owner of that recipe, dependency
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
uv run --frozen --no-sync python scripts/docs/build_config.py
uv run --frozen --no-sync zensical build -f mkdocs.gen.yml --strict

# Zensical renders an unresolvable [`name`][identifier] cross-reference as
# literal bracket text and stays green even under --strict (mkdocs-autorefs
# used to warn, and strict mode failed). The generated API index relies on
# such references, so catch the failure mode here.
if grep -rn --include='*.html' -F '[<code>' site/ > /dev/null; then
    echo "error: unresolved cross-references rendered as literal text:" >&2
    grep -rn --include='*.html' -Fo -m 1 '[<code>' site/ | head -20 >&2
    exit 1
fi

uv run --frozen --no-sync python scripts/docs/llms_txt.py --site-dir site
