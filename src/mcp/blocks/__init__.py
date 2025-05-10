"""Block classes for the MCP server.

This module contains block classes for the MCP server.
"""

# Import all built-in block classes here

# Import registry—public helpers ensure the module is loaded for side-effects.
from .registry import (
    UnknownBlockKindError,
    get_block_class,
    is_block_kind_registered,
    list_block_kinds,
    register_block,
)

__all__ = [
    "register_block",
    "get_block_class",
    "list_block_kinds",
    "is_block_kind_registered",
    "UnknownBlockKindError",
]
