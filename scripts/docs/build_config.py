"""Produce the concrete Zensical build config from ``mkdocs.yml``.

Zensical builds from ``mkdocs.yml`` directly, but it has no equivalent of
``mkdocs-literate-nav``: the ``API Reference`` navigation has to be materialised
as explicit entries. This script regenerates the ``docs/api/`` tree (via
:mod:`gen_ref_pages`) and writes ``mkdocs.gen.yml`` with the real API nav
spliced in — that generated file is what ``zensical build``/``serve`` consumes.

Usage:
    python scripts/docs/build_config.py [--site-dir DIR] [--output FILE]
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Both scripts live in this directory, which Python puts on sys.path[0] when
# `build_config.py` is run directly (its documented invocation).
import gen_ref_pages
import yaml

ROOT = Path(__file__).parent.parent.parent


def build_config(output: Path, site_dir: str | None = None) -> None:
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))

    api_nav = gen_ref_pages.generate()
    for entry in config["nav"]:
        if isinstance(entry, dict) and "API Reference" in entry:
            entry["API Reference"] = api_nav
            break
    else:
        raise SystemExit("build_config: no 'API Reference' entry found in mkdocs.yml nav")

    if site_dir is not None:
        config["site_dir"] = site_dir

    output.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", default=None, help="Override the build output directory.")
    parser.add_argument("--output", default=str(ROOT / "mkdocs.gen.yml"), help="Where to write the generated config.")
    args = parser.parse_args()
    build_config(Path(args.output), args.site_dir)


if __name__ == "__main__":
    main()
