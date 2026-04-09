"""Shared helpers for MQTT-style topic pattern matching.

Both the client (for subscription filtering) and the server (for the
subscription registry and retained-event store) need to compile MQTT-style
topic patterns into regular expressions. Keeping the implementation here
avoids a client -> server import and guarantees identical semantics on both
sides of the protocol.
"""

from __future__ import annotations

import re

__all__ = ["pattern_to_regex"]


def pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert an MQTT-style topic pattern to a compiled regex.

    ``+`` becomes a single-segment match, ``#`` becomes a greedy
    multi-segment match (only valid as the final segment).
    """
    parts = pattern.split("/")
    regex_parts: list[str] = []
    for i, part in enumerate(parts):
        if part == "#":
            if i != len(parts) - 1:
                raise ValueError("'#' wildcard is only valid as the last segment")
            # # matches zero or more trailing segments.
            # If preceding segments exist, the / before # is optional
            # so "myapp/#" matches both "myapp" and "myapp/anything".
            # If # is the sole segment, it matches everything.
            if regex_parts:
                return re.compile("^" + "/".join(regex_parts) + "(/.*)?$")
            else:
                return re.compile("^.*$")
        elif part == "+":
            regex_parts.append("[^/]+")
        else:
            regex_parts.append(re.escape(part))
    return re.compile("^" + "/".join(regex_parts) + "$")
