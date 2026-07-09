"""Produce the concrete Zensical build config from `mkdocs.yml`.

Zensical builds from `mkdocs.yml` directly, but it has no equivalent of
mkdocs-literate-nav: the "API Reference" navigation has to be materialised
as explicit entries. This script regenerates the `docs/api/` tree (via
gen_ref_pages) and writes `mkdocs.gen.yml` with the real API nav spliced
in — that generated file is what `zensical build`/`serve` consumes.

Usage:
    python scripts/docs/build_config.py
"""

from __future__ import annotations

from pathlib import Path

# Both scripts live in this directory, which Python puts on sys.path[0] when
# `build_config.py` is run directly (its documented invocation).
import gen_ref_pages
import yaml

ROOT = Path(__file__).parent.parent.parent


def _missing_nav_pages(nav: list, docs_dir: Path) -> list[str]:
    """Collect nav page references that don't exist under the docs dir.

    Zensical (0.0.48) ships a nav entry for a nonexistent page as a broken
    link without any diagnostic, even under --strict — MkDocs aborted the
    build. Validating here keeps that guarantee: the concrete config never
    leaves this script referencing a page that isn't there.
    """
    missing: list[str] = []
    for entry in nav:
        value = next(iter(entry.values())) if isinstance(entry, dict) else entry
        if isinstance(value, list):
            missing.extend(_missing_nav_pages(value, docs_dir))
        elif "://" not in value and not (docs_dir / value).is_file():
            missing.append(value)
    return missing


def build_config() -> None:
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))

    api_nav = gen_ref_pages.generate()
    if not api_nav:
        raise SystemExit("build_config: gen_ref_pages produced no API pages — did the src/ layout move?")
    for entry in config["nav"]:
        if isinstance(entry, dict) and "API Reference" in entry:
            entry["API Reference"] = api_nav
            break
    else:
        raise SystemExit("build_config: no 'API Reference' entry found in mkdocs.yml nav")

    if missing := _missing_nav_pages(config["nav"], ROOT / "docs"):
        raise SystemExit(f"build_config: nav references pages that don't exist under docs/: {missing}")

    output = ROOT / "mkdocs.gen.yml"
    output.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")


if __name__ == "__main__":
    build_config()
