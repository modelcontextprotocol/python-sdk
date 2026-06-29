"""Server-side caching hints (SEP-2549, protocol revision 2026-07-28).

Results for the cacheable methods carry `ttlMs`/`cacheScope` freshness hints.
A handler sets them by returning a result with explicit `ttl_ms`/`cache_scope`
values; `Server(cache_hints={method: CacheHint(...)})` fills them for handlers
that don't. Fields the handler set win, per field, so a server-wide hint never
overrides a handler's explicit choice.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import mcp_types as types
from mcp_types.methods import CACHEABLE_METHODS, CacheableMethod

__all__ = ["CACHEABLE_METHODS", "CacheHint", "CacheableMethod", "apply_cache_hint", "validate_cache_hints"]


@dataclass(frozen=True, slots=True)
class CacheHint:
    """Freshness hint for one cacheable method's results.

    `ttl_ms` is how long, in milliseconds, a client may consider the result
    fresh (`0` means immediately stale). `scope` is whether a cached result may
    be shared across authorization contexts (`"public"`) or only reused within
    the one that produced it (`"private"`).
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
    """Fill `ttl_ms`/`cache_scope` on `result` from `hint`.

    Per-field: a field the handler set explicitly - even to its default value,
    tracked via `model_fields_set` - is left alone; only unset fields take the
    hint. A handler constructing results with `model_construct` bypasses that
    tracking and is treated as having set nothing.
    """
    update: dict[str, int | str] = {}
    if "ttl_ms" not in result.model_fields_set:
        update["ttl_ms"] = hint.ttl_ms
    if "cache_scope" not in result.model_fields_set:
        update["cache_scope"] = hint.scope
    return result.model_copy(update=update) if update else result


def validate_cache_hints(cache_hints: Mapping[Any, Any] | None) -> dict[str, CacheHint]:
    """Validate a `cache_hints` constructor argument into a plain dict.

    The `Server`/`MCPServer` signatures already close the key set and value
    type for type-checked callers; this runtime gate is deliberately loose in
    its parameter so it covers everyone else (e.g. a map deserialized from
    config) - a bad entry fails at construction, not on the first request to
    that method.

    Raises:
        ValueError: If a key is not a cacheable method.
        TypeError: If a value is not a `CacheHint`.
    """
    if cache_hints is None:
        return {}
    # Keys come from an untyped mapping, so format via repr: a non-string key
    # must produce this ValueError too, not a TypeError from sorted/join.
    unknown = sorted(repr(method) for method in cache_hints if method not in CACHEABLE_METHODS)
    if unknown:
        raise ValueError(f"cache_hints keys must be cacheable methods (see CacheableMethod); got: {', '.join(unknown)}")
    validated: dict[str, CacheHint] = {}
    for method, hint in cache_hints.items():
        if not isinstance(hint, CacheHint):
            raise TypeError(f"cache_hints[{method!r}] must be a CacheHint, got {type(hint).__name__}")
        validated[method] = hint
    return validated
