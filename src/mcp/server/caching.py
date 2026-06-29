"""Server-side caching hints (SEP-2549, protocol revision 2026-07-28).

`Server(cache_hints={method: CacheHint(...)})` fills `ttlMs`/`cacheScope` on
cacheable results per field, never overriding a value the handler set explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, TypeVar, get_args

import mcp_types as types

__all__ = ["CACHEABLE_METHODS", "CacheHint", "CacheableMethod", "apply_cache_hint", "validate_cache_hints"]

CacheableMethod = Literal[
    "prompts/list",
    "resources/list",
    "resources/read",
    "resources/templates/list",
    "server/discover",
    "tools/list",
]
"""Methods whose results carry `ttlMs`/`cacheScope`; a closed set, fixed by the spec."""

CACHEABLE_METHODS: Final[frozenset[str]] = frozenset(get_args(CacheableMethod))
"""Runtime mirror of `CacheableMethod`, for callers the type checker can't see."""


@dataclass(frozen=True, slots=True)
class CacheHint:
    """Freshness hint for one cacheable method's results.

    `ttl_ms` is how long (in ms) a client may treat the result as fresh, `0` meaning
    immediately stale; `scope` is whether a cached result may be shared across
    authorization contexts (`"public"`) or only the one that produced it (`"private"`).
    """

    ttl_ms: int = 0
    scope: Literal["public", "private"] = "private"

    def __post_init__(self) -> None:
        if self.ttl_ms < 0:
            raise ValueError(f"ttl_ms must be >= 0, got {self.ttl_ms}")
        if self.scope not in ("public", "private"):
            raise ValueError(f"scope must be 'public' or 'private', got {self.scope!r}")


CacheableResultT = TypeVar("CacheableResultT", bound=types.CacheableResult)


def apply_cache_hint(result: CacheableResultT, hint: CacheHint) -> CacheableResultT:
    """Fill unset `ttl_ms`/`cache_scope` fields on `result` from `hint`.

    Explicitly set fields win even at their defaults (per `model_fields_set`);
    `model_construct` bypasses that tracking and counts as having set nothing.
    """
    update: dict[str, int | str] = {}
    if "ttl_ms" not in result.model_fields_set:
        update["ttl_ms"] = hint.ttl_ms
    if "cache_scope" not in result.model_fields_set:
        update["cache_scope"] = hint.scope
    return result.model_copy(update=update) if update else result


def validate_cache_hints(cache_hints: Mapping[Any, Any] | None) -> dict[str, CacheHint]:
    """Validate a `cache_hints` constructor argument into a plain dict.

    Deliberately loose parameter type: covers callers the `Server`/`MCPServer`
    signatures can't (e.g. maps from config), failing at construction rather
    than on the first request.

    Raises:
        ValueError: If a key is not a cacheable method.
        TypeError: If a value is not a `CacheHint`.
    """
    if cache_hints is None:
        return {}
    unknown = sorted(method for method in cache_hints if method not in CACHEABLE_METHODS)
    if unknown:
        raise ValueError(f"cache_hints keys must be cacheable methods (see CacheableMethod); got: {', '.join(unknown)}")
    validated: dict[str, CacheHint] = {}
    for method, hint in cache_hints.items():
        if not isinstance(hint, CacheHint):
            raise TypeError(f"cache_hints[{method!r}] must be a CacheHint, got {type(hint).__name__}")
        validated[method] = hint
    return validated
