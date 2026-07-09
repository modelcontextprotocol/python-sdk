---
name: verify
description: Build and inspect this repo's docs site to verify docs-toolchain changes end-to-end.
---

# Verifying changes in this repo

## Docs toolchain (mkdocs.yml, scripts/docs/, docs/)

The surface is the built site. Build it and look at the output:

```bash
uv sync --frozen --group docs
bash scripts/docs/build.sh        # strict; fails on any build issue (~25s cold)
```

- Output lands in `site/`. `docs/api/` and `mkdocs.gen.yml` are regenerated
  by the build; `.cache/` makes rebuilds incremental — `rm -rf site .cache`
  for a cold build.
- API pages: check heading structure with `grep -c '<h2' site/api/<page>/index.html`
  and that autoref links resolved: unresolved refs render as literal
  `[<code>X</code>][target]` text and `zensical build --strict` does NOT
  flag them — grep the built page for `\[<code>` to catch them.
- `zensical serve` exists for interactive checks; the build config it needs
  is `mkdocs.gen.yml` (generated), not `mkdocs.yml`.

## Library code (src/)

Drive through the public package boundary, e.g. an in-memory
`Client(server)` script run with `uv run --frozen python <script>` (see
`tests/client/test_client.py` for the canonical wiring). Don't verify by
running the test suite — that's CI's job.
