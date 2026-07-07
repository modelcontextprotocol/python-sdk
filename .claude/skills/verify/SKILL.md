---
name: verify
description: How to build and observe this repo's docs and library surfaces end-to-end.
---

# Verifying changes in this repo

## Library code (src/mcp, src/mcp-types)

Drive through the public package boundary with an in-memory client —
`tests/client/test_client.py` shows the canonical `Client(server)` pattern.
Write a small sample script that imports `mcp` (not `./src/...` paths) and run
it with `uv run --frozen python <script>`.

## Docs (mkdocs pipeline)

```bash
uv run --frozen mkdocs build -d /tmp/site-mkdocs   # strict: true is in mkdocs.yml
```

Inspect the built HTML under the output dir; `docs/api/` pages are virtual
(mkdocs-gen-files), so they exist only in the site output.

## Docs (zensical spike pipeline)

```bash
uv run --frozen python scripts/gen_api_pages.py      # writes docs/api/ + mkdocs.zensical.yml
uv run --frozen zensical build --strict -f mkdocs.zensical.yml   # output in site/
```

Both `docs/api/` and `mkdocs.zensical.yml` are generated and gitignored.
Spot-check `site/api/mcp/index.html` for `doc doc-object` (mkdocstrings
rendered) and a prose page for inlined `docs_src/` snippet content. Known
gap: the zensical site has no `llms.txt`/`llms-full.txt` (zensical ignores
`hooks:`). Before returning to the mkdocs pipeline, run
`rm -rf docs/api mkdocs.zensical.yml` — a stale `docs/api/` page for a
since-deleted module fails the strict mkdocs build.

## Gotchas

- If the dev group's git dep (`strict-no-cover`) is unreachable (proxy-scoped
  containers), use `uv sync --only-group docs` and pass `--no-sync` to
  `uv run`.
- Zensical requires mkdocstrings >= 1.0; 0.30 crashes with
  `KeyError: 'mkdocs-autorefs'`.
