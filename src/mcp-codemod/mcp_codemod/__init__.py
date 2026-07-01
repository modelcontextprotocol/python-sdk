"""Automated rewrites for migrating code between major versions of the MCP Python SDK.

Run as a tool (`uvx mcp-codemod v1-to-v2 ./src`) or call `transform(source)` as a library.

Rewrites are conservative by construction: names are resolved through the file's
imports rather than matched as text, and anything whose correct rewrite depends on
information outside the file gets an inline `# mcp-codemod:` comment instead of a
guess; `grep -rn '# mcp-codemod:'` after a run lists everything left for a human.
"""

from mcp_codemod._transformer import MARKER, Diagnostic, Result, transform

__all__ = ["MARKER", "Diagnostic", "Result", "transform"]
