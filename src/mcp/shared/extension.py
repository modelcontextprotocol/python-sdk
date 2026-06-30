"""Extension-identifier grammar shared by the server and client extension surfaces.

Server extensions (`mcp.server.extension`) and client extensions
(`mcp.client.extension`) carry the same kind of identifier; this module is the
one source of truth for its validation.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["validate_extension_identifier"]

# Extension identifiers follow the `_meta` key grammar with a mandatory prefix
# (SEP-2133 / basic/index.mdx): dot-separated labels, each starting with a
# letter and ending with a letter or digit (hyphens interior), then `/`, then a
# name that starts and ends alphanumeric (`.`/`_`/`-` interior).
_LABEL = r"[A-Za-z](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_IDENTIFIER_RE = re.compile(rf"{_LABEL}(?:\.{_LABEL})*/{_NAME}")


def validate_extension_identifier(identifier: Any, *, owner: str) -> None:
    """Raise `TypeError` unless `identifier` is a `vendor-prefix/name` string.

    SEP-2133 requires extension identifiers to carry a reverse-DNS prefix.
    """
    if not isinstance(identifier, str) or not _IDENTIFIER_RE.fullmatch(identifier):
        raise TypeError(
            f"{owner}.identifier must be a `vendor-prefix/name` string "
            f"(reverse-DNS prefix required), got {identifier!r}"
        )
