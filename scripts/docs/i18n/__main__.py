"""Entrypoint: `python scripts/docs/i18n <command>` from the repository root.

Running the package directory puts this directory on `sys.path`; the tool's
modules and the sibling docs scripts are imported through `scripts/docs`, so
that directory is added ahead of the imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from i18n.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
