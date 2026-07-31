"""Atomic writes for the tool's generated files.

A translation run or a `prune` that dies half-way through a plain
`write_text` would leave a truncated `state.json`, `nav.yml` or translated
page behind, and the next command would then refuse to parse it. Writing the
new bytes to a sibling temporary file, syncing it, and renaming it over the
target makes every generated file either its old content or its new content,
never a torn one — the rename is atomic on the same filesystem.
"""

import contextlib
import os
import tempfile
from pathlib import Path


def write_text_atomically(path: Path, text: str) -> None:
    """Write `text` to `path` such that an interruption leaves the old file or the new one, never a torn one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
