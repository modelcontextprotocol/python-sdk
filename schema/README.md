# Vendored protocol schemas

JSON Schema files for each protocol version the SDK has a wire-shape surface
package for, vendored from the [spec repository] at the commit recorded in
`PINNED.json`. `scripts/gen_surface_types.py` reads these to regenerate
`src/mcp/types/v<version>/__init__.py`; CI runs the generator with `--check`.

To bump: drop the new `schema.json` here as `<protocol-version>.json`, update
the matching entry in `PINNED.json` (commit + sha256), and run
`uv run --frozen --group codegen python scripts/gen_surface_types.py`.

[spec repository]: https://github.com/modelcontextprotocol/modelcontextprotocol
