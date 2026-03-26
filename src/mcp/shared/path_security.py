"""Filesystem path safety primitives for resource handlers.

These functions help MCP servers defend against path-traversal attacks
when extracted URI template parameters are used in filesystem
operations. They are standalone utilities usable from both the
high-level :class:`~mcp.server.mcpserver.MCPServer` and lowlevel server
implementations.

The canonical safe pattern::

    from mcp.shared.path_security import safe_join

    @mcp.resource("file://docs/{+path}")
    def read_doc(path: str) -> str:
        return safe_join("/data/docs", path).read_text()
"""

from pathlib import Path

__all__ = ["PathEscapeError", "contains_path_traversal", "is_absolute_path", "safe_join"]


class PathEscapeError(ValueError):
    """Raised by :func:`safe_join` when the resolved path escapes the base."""


def contains_path_traversal(value: str) -> bool:
    r"""Check whether a value, treated as a relative path, escapes its origin.

    This is a **base-free** check: it does not know the sandbox root, so
    it detects only whether ``..`` components would move above the
    starting point. Use :func:`safe_join` when you know the root — it
    additionally catches symlink escapes and absolute-path injection.

    The check is component-based: ``..`` is dangerous only as a
    standalone path segment, not as a substring. Both ``/`` and ``\``
    are treated as separators.

    Example::

        >>> contains_path_traversal("a/b/c")
        False
        >>> contains_path_traversal("../etc")
        True
        >>> contains_path_traversal("a/../../b")
        True
        >>> contains_path_traversal("a/../b")
        False
        >>> contains_path_traversal("1.0..2.0")
        False
        >>> contains_path_traversal("..")
        True

    Args:
        value: A string that may be used as a filesystem path.

    Returns:
        ``True`` if the path would escape its starting directory.
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
    r"""Check whether a value is an absolute filesystem path.

    Absolute paths are dangerous when joined onto a base: in Python,
    ``Path("/data") / "/etc/passwd"`` yields ``/etc/passwd`` — the
    absolute right-hand side silently discards the base.

    Detects POSIX absolute (``/foo``), Windows drive (``C:\foo``),
    and Windows UNC/absolute (``\\server\share``, ``\foo``).

    Example::

        >>> is_absolute_path("relative/path")
        False
        >>> is_absolute_path("/etc/passwd")
        True
        >>> is_absolute_path("C:\\Windows")
        True
        >>> is_absolute_path("")
        False

    Args:
        value: A string that may be used as a filesystem path.

    Returns:
        ``True`` if the path is absolute on any common platform.
    """
    if not value:
        return False
    if value[0] in ("/", "\\"):
        return True
    # Windows drive letter: C:, C:\, C:/
    if len(value) >= 2 and value[1] == ":" and value[0].isalpha():
        return True
    return False


def safe_join(base: str | Path, *parts: str) -> Path:
    """Join path components onto a base, rejecting escapes.

    Resolves the joined path and verifies it remains within ``base``.
    This is the **gold-standard** check: it catches ``..`` traversal,
    absolute-path injection, and symlink escapes that the base-free
    checks cannot.

    Example::

        >>> safe_join("/data/docs", "readme.txt")
        PosixPath('/data/docs/readme.txt')
        >>> safe_join("/data/docs", "../../../etc/passwd")
        Traceback (most recent call last):
        ...
        PathEscapeError: ...

    Args:
        base: The sandbox root. May be relative; it will be resolved.
        parts: Path components to join. Each is checked for null bytes
            and absolute form before joining.

    Returns:
        The resolved path, guaranteed to be within ``base``.

    Raises:
        PathEscapeError: If any part contains a null byte, any part is
            absolute, or the resolved path is not contained within the
            resolved base.
    """
    base_resolved = Path(base).resolve()

    for part in parts:
        # Null bytes pass through Path construction but fail at the
        # syscall boundary with a cryptic error. Reject here so callers
        # get a clear PathEscapeError instead.
        if "\0" in part:
            raise PathEscapeError(f"Path component contains a null byte; refusing to join onto {base_resolved}")
        # Absolute parts would silently discard everything to the left
        # in Path's / operator.
        if is_absolute_path(part):
            raise PathEscapeError(f"Path component {part!r} is absolute; refusing to join onto {base_resolved}")

    target = base_resolved.joinpath(*parts).resolve()

    if not target.is_relative_to(base_resolved):
        raise PathEscapeError(f"Path {target} escapes base {base_resolved}")

    return target
