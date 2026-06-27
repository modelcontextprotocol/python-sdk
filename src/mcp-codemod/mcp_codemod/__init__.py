"""Automated rewrites for migrating code between major versions of the MCP Python SDK.

Run it as a tool:

    uvx mcp-codemod v1-to-v2 ./src

or call it as a library:

    from mcp_codemod import transform

    result = transform(source)
    print(result.code)

Every rewrite is conservative by construction: names are resolved through the file's
imports rather than matched as text, and anything whose correct rewrite depends on
information that is not in the file gets an inline `# mcp-codemod:` comment instead
of a guess. `grep -rn '# mcp-codemod:'` after a run is the complete list of what is
left for a human.
"""

from mcp_codemod._transformer import MARKER, Diagnostic, Result, transform

__all__ = ["MARKER", "Diagnostic", "Result", "transform"]
