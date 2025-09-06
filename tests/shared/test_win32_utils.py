"""Windows-specific test utilities."""


def escape_path_for_python(path: str) -> str:
    """Escape a file path for use in Python code strings.

    Converts backslashes to forward slashes which work on all platforms
    and don't need escaping in Python strings.
    """
    return repr(path.replace("\\", "/"))
