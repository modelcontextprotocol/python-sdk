"""Generate llms.txt, llms-full.txt, and per-page markdown (https://llmstxt.org/).

Zensical has no equivalent of MkDocs' build hooks, so this runs as a standalone
post-build step over the source tree (``mkdocs.yml`` + ``docs/``) and writes
three kinds of artifact into the built ``site/``:

- ``llms.txt``: a markdown index of the documentation, one link per page,
  grouped by nav section.
- a ``.md`` rendition of every prose page next to its HTML (e.g.
  ``servers/tools/index.md``), which is what the llms.txt links point at.
- ``llms-full.txt``: every prose page concatenated for single-fetch consumption.

Page markdown is the source markdown with ``--8<--`` snippet includes resolved
(so the ``docs_src/`` code examples appear inline) and relative links rewritten
to absolute URLs. The API reference pages under ``api/`` are mkdocstrings stubs
with no prose source, so they are linked as rendered HTML from an Optional
section instead of being embedded.

Usage:
    python scripts/docs/llms_txt.py --site-dir site
"""

from __future__ import annotations

import argparse
import posixpath
import re
from pathlib import Path, PurePosixPath

import yaml

ROOT = Path(__file__).parent.parent.parent
DOCS = ROOT / "docs"

# Pages with no markdown source, linked as HTML under "## Optional".
_OPTIONAL_PAGES = [
    ("api/mcp/index.md", "mcp API reference", "Auto-generated API reference for the mcp package (rendered HTML)"),
    (
        "api/mcp_types/index.md",
        "mcp-types API reference",
        "Auto-generated API reference for the mcp-types package (rendered HTML)",
    ),
]

_SNIPPET_LINE = re.compile(r'^(?P<indent>[ \t]*)--8<-- "(?P<path>[^"\n]+)"$', flags=re.MULTILINE)
_MD_LINK = re.compile(r'(\]\()([^)\s]+\.md)(#[^)\s]*)?( +"[^"]*")?(\))')


class _BuildError(Exception):
    """A recoverable problem that should fail the docs build with a clear message."""


def _dest_md_uri(src_uri: str) -> str:
    """Map a source page (``servers/tools.md``) to its built rendition (``servers/tools/index.md``)."""
    path = PurePosixPath(src_uri)
    directory = path.parent if path.stem == "index" else path.parent / path.stem
    return "index.md" if directory == PurePosixPath(".") else f"{directory}/index.md"


def _page_url(src_uri: str) -> str:
    """The directory URL of a page relative to the site root (``servers/tools/``, ``""`` for the home page)."""
    return _dest_md_uri(src_uri).removesuffix("index.md")


def _walk_nav(nav: list, prose: dict[str, str | None], sections: list[tuple[str, list[str]]]) -> list[str]:
    """Split the nav into a flat list of top-level pages and titled sections.

    Populates ``prose`` (src_uri -> nav title, or ``None`` to fall back to the
    page's H1) and ``sections`` ((title, [src_uri]) in nav order), and returns
    the top-level page src_uris. API and section-index bare entries are skipped.
    """
    top_level: list[str] = []
    for entry in nav:
        title, value = next(iter(entry.items())) if isinstance(entry, dict) else (None, entry)
        if isinstance(value, list):
            pages = _section_pages(value, prose)
            if pages:
                assert title is not None
                sections.append((title, pages))
        elif value.endswith(".md") and not value.startswith("api/"):
            prose[value] = title
            top_level.append(value)
    return top_level


def _section_pages(items: list, prose: dict[str, str | None]) -> list[str]:
    pages: list[str] = []
    for entry in items:
        title, value = next(iter(entry.items())) if isinstance(entry, dict) else (None, entry)
        if isinstance(value, list):
            pages.extend(_section_pages(value, prose))
        elif value.endswith(".md") and not value.startswith("api/"):
            prose[value] = title
            pages.append(value)
    return pages


def _resolve_snippets(markdown: str, src_uri: str) -> str:
    def include(match: re.Match[str]) -> str:
        indent, path = match["indent"], match["path"]
        # Reject snippet paths that escape the repo root (mirrors the snippets
        # extension's restrict_base_path).
        resolved = (ROOT / path).resolve()
        if not resolved.is_relative_to(ROOT.resolve()):
            raise _BuildError(f"llms_txt: snippet path {path!r} in {src_uri} escapes the repo root")
        try:
            content = resolved.read_text(encoding="utf-8").rstrip("\n")
        except OSError as exc:
            raise _BuildError(f"llms_txt: cannot read snippet {path!r} in {src_uri}") from exc
        if path.endswith(".py"):
            content = f"# {path}\n{content}"
        if indent:
            content = "\n".join(indent + line if line else line for line in content.split("\n"))
        return content

    resolved, substitutions = _SNIPPET_LINE.subn(include, markdown)
    if substitutions != sum("--8<--" in line for line in markdown.splitlines()):
        raise _BuildError(f"llms_txt: unresolved snippet include in {src_uri}")
    return resolved


def _rewrite_links(markdown: str, src_uri: str, site_url: str, prose: dict[str, str | None]) -> str:
    src_dir = posixpath.dirname(src_uri)

    def rewrite(match: re.Match[str]) -> str:
        opening, target, anchor, title, closing = match.groups()
        if "://" in target:
            return match.group(0)
        linked = posixpath.normpath(posixpath.join(src_dir, target))
        if not (DOCS / linked).exists():
            raise _BuildError(f"llms_txt: cannot resolve link target {target!r} in {src_uri}")
        # Pages without a markdown rendition (the api/ stubs) link to their HTML instead.
        url = _dest_md_uri(linked) if linked in prose else _page_url(linked)
        return f"{opening}{site_url}{url}{anchor or ''}{title or ''}{closing}"

    return _MD_LINK.sub(rewrite, markdown)


def _title(src_uri: str, nav_title: str | None, body: str) -> str:
    if nav_title is not None:
        return nav_title
    match = re.search(r"^\s*# (.+)$", body, flags=re.MULTILINE)
    if match is None:
        raise _BuildError(f"llms_txt: page {src_uri} has no nav title and no H1")
    return match.group(1).strip()


def generate(site_dir: Path) -> None:
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    site_url = config["site_url"].rstrip("/") + "/"

    prose: dict[str, str | None] = {}
    sections: list[tuple[str, list[str]]] = []
    top_level = _walk_nav(config["nav"], prose, sections)
    ordered: list[tuple[str, list[str]]] = ([("Docs", top_level)] if top_level else []) + sections

    rendered: dict[str, str] = {}
    for src_uri in prose:
        markdown = (DOCS / src_uri).read_text(encoding="utf-8")
        markdown = _resolve_snippets(markdown, src_uri)
        rendered[src_uri] = _rewrite_links(markdown, src_uri, site_url, prose)

    index = [f"# {config['site_name']}", "", f"> {config['site_description']}", ""]
    full: list[str] = []
    for section_title, pages in ordered:
        index += [f"## {section_title}", ""]
        for src_uri in pages:
            markdown = rendered[src_uri]
            md_uri = _dest_md_uri(src_uri)
            (site_dir / md_uri).parent.mkdir(parents=True, exist_ok=True)
            (site_dir / md_uri).write_text(markdown, encoding="utf-8")

            title = _title(src_uri, prose[src_uri], markdown)
            index.append(f"- [{title}]({site_url}{md_uri})")

            body, h1_found = re.subn(r"\A\s*# .+\n", "", markdown)
            if not h1_found:
                raise _BuildError(f"llms_txt: page {src_uri} does not start with an H1")
            full += [f"# {title}", "", f"Source: {site_url}{_page_url(src_uri)}", "", body.strip(), ""]
        index.append("")

    index += ["## Optional", ""]
    for src_uri, title, description in _OPTIONAL_PAGES:
        if not (DOCS / src_uri).exists():
            raise _BuildError(f"llms_txt: optional page {src_uri} not found (run gen_ref_pages first)")
        index.append(f"- [{title}]({site_url}{_page_url(src_uri)}): {description}")
    index.append("")

    (site_dir / "llms.txt").write_text("\n".join(index), encoding="utf-8")
    (site_dir / "llms-full.txt").write_text("\n".join(full), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", default=str(ROOT / "site"), help="The built site directory to write into.")
    args = parser.parse_args()
    try:
        generate(Path(args.site_dir))
    except _BuildError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
