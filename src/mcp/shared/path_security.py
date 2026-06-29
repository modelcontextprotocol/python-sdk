"""Filesystem path safety primitives for resource handlers.

Helpers to reject paths that would resolve outside the served root when
extracted URI template parameters are used in filesystem operations.
"""

import string
from pathlib import Path

__all__ = ["PathEscapeError", "contains_path_traversal", "is_absolute_path", "safe_join"]


class PathEscapeError(ValueError):
    """Raised by `safe_join` when the resolved path escapes the base."""


def contains_path_traversal(value: str) -> bool:
    r"""Check whether a value, treated as a relative path, escapes its origin.

    Base-free, string-level check: it only detects `..` segments climbing above
    the starting point. `..` counts as a whole segment, not a substring
    (`a/../b` and `1.0..2.0` are safe); both `/` and `\` are separators. It does
    not model platform normalisation (e.g. Win32 stripping trailing dots and
    spaces). When the root is known, use `safe_join`, which resolves through the
    OS and additionally catches symlink escapes and absolute-path injection.
    """
    depth = 0
    for part in value.replace("\\", "/").split("/"):
        if part == "..":
            depth -= 1
            if depth < 0:
                return True
        elif part and part != ".":
            depth += 1
    return False


def is_absolute_path(value: str) -> bool:
    r"""Check whether a value is an absolute path on any common platform.

    Absolute paths are dangerous when joined onto a base: in Python,
    `Path("/data") / "/etc/passwd"` yields `/etc/passwd`. Detects POSIX absolute
    (`/foo`), Windows drive-absolute (`C:\foo`) and drive-relative (`C:foo`),
    and Windows UNC/root-relative (`\\server\share`, `\foo`).
    """
    if not value:
        return False
    if value[0] in ("/", "\\"):
        return True
    # Drive-relative C:foo discards the join base when drives differ, so flag it even
    # though PureWindowsPath.is_absolute() is False. Single-letter-prefixed identifiers
    # like "x:y" also match — opt out via ResourceSecurity(exempt_params=).
    if len(value) >= 2 and value[1] == ":" and value[0] in string.ascii_letters:
        return True
    return False


def safe_join(base: str | Path, *parts: str) -> Path:
    """Join path components onto a base, rejecting escapes.

    Resolves the joined path and verifies it stays within `base` (which may be
    relative; it is resolved too), catching `..` traversal, absolute-path
    injection, and symlink escapes that the base-free checks cannot. The symlink
    check is point-in-time: a directory swapped for a symlink between this call
    and the caller's open is not re-checked — handlers serving a concurrently
    modified tree should also open with `O_NOFOLLOW` or use platform
    path-confinement primitives.

    Returns:
        The resolved path, verified to be within `base` at resolution time.

    Raises:
        PathEscapeError: If any part contains a null byte or is absolute, or the
            resolved path is not contained within the resolved base.
    """
    base_resolved = Path(base).resolve()

    for part in parts:
        # Null bytes pass Path construction but fail at the syscall boundary with
        # a cryptic error; reject here with a clear PathEscapeError instead.
        if "\0" in part:
            raise PathEscapeError(f"Path component contains a null byte; refusing to join onto {base_resolved}")
        if is_absolute_path(part):
            raise PathEscapeError(f"Path component {part!r} is absolute; refusing to join onto {base_resolved}")

    target = base_resolved.joinpath(*parts).resolve()

    if not target.is_relative_to(base_resolved):
        raise PathEscapeError(f"Path {target} escapes base {base_resolved}")

    return target
