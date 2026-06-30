"""Generate llms.txt, llms-full.txt, and per-page markdown (https://llmstxt.org/).

The hook publishes three artifacts into the built site:

- `llms.txt`: a markdown index of the documentation, one link per page,
  grouped by nav section.
- a `.md` rendition of every prose page next to its HTML (e.g.
  `server/index.md`), which is what the llms.txt links point at.
- `llms-full.txt`: every prose page concatenated for single-fetch consumption.

Page markdown is the source markdown with `--8<--` snippet includes resolved
and relative links rewritten to absolute URLs. The API reference page
(`api.md`) is a mkdocstrings stub with no markdown source, so it is linked as
rendered HTML from an Optional section instead of being embedded.

Incremental builds (`mkdocs build --dirty`) are rejected: they skip unmodified
pages, which would silently truncate the generated artifacts.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.exceptions import PluginError
from mkdocs.structure.files import File, Files
from mkdocs.structure.nav import Navigation, Section
from mkdocs.structure.pages import Page

# Pages with no markdown source, linked as HTML under "## Optional".
_OPTIONAL_PAGES = [
    ("api.md", "API reference", "Auto-generated API reference for the mcp package (rendered HTML)"),
]

_SNIPPET_LINE = re.compile(r'^(?P<indent>[ \t]*)--8<-- "(?P<path>[^"\n]+)"$', flags=re.MULTILINE)
_MD_LINK = re.compile(r'(\]\()([^)\s]+\.md)(#[^)\s]*)?( +"[^"]*")?(\))')


@dataclass
class _State:
    page_markdown: dict[str, str] = field(default_factory=dict)
    rendition_uris: set[str] = field(default_factory=set)
    nav: Navigation | None = None
    files: Files | None = None


_state = _State()


def _site_url(config: MkDocsConfig) -> str:
    assert config.site_url is not None
    return config.site_url.rstrip("/") + "/"


def _md_uri(file: File) -> str:
    return re.sub(r"\.html$", ".md", file.dest_uri)


def on_config(config: MkDocsConfig) -> None:
    # `mkdocs serve` rebuilds reuse the imported module; start each build clean.
    _state.page_markdown.clear()
    _state.rendition_uris.clear()
    _state.nav = _state.files = None


def on_nav(nav: Navigation, config: MkDocsConfig, files: Files) -> None:
    _state.nav = nav
    _state.files = files
    _state.rendition_uris.update(page.file.src_uri for page in nav.pages if page.file.src_uri != "api.md")


def on_page_markdown(markdown: str, page: Page, config: MkDocsConfig, files: Files) -> str | None:
    if page.file.src_uri not in _state.rendition_uris:
        return None

    # Same anchor as the pymdownx.snippets `base_path` in mkdocs.yml.
    repo_root = Path(config.config_file_path).parent

    def include(match: re.Match[str]) -> str:
        indent, path = match["indent"], match["path"]
        # Mirror the snippets extension's restrict_base_path: reject paths
        # that resolve outside the repo root.
        resolved_path = (repo_root / path).resolve()
        if not resolved_path.is_relative_to(repo_root.resolve()):
            raise PluginError(f"llms_txt: snippet path {path!r} in {page.file.src_uri} escapes the repo root")
        try:
            content = resolved_path.read_text(encoding="utf-8").rstrip("\n")
        except OSError as exc:
            raise PluginError(f"llms_txt: cannot read snippet {path!r} in {page.file.src_uri}") from exc
        # Keep a pointer to the embedded file so readers can find it on disk.
        if path.endswith(".py"):
            content = f"# {path}\n{content}"
        if indent:
            content = "\n".join(indent + line if line else line for line in content.split("\n"))
        return content

    resolved, substitutions = _SNIPPET_LINE.subn(include, markdown)
    if substitutions != sum("--8<--" in line for line in markdown.splitlines()):
        raise PluginError(f"llms_txt: unresolved snippet include in {page.file.src_uri}")

    site_url = _site_url(config)
    src_dir = posixpath.dirname(page.file.src_uri)

    def rewrite(match: re.Match[str]) -> str:
        opening, target, anchor, title, closing = match.groups()
        if "://" in target:
            return match.group(0)
        linked = files.get_file_from_path(posixpath.normpath(posixpath.join(src_dir, target)))
        if linked is None:
            raise PluginError(f"llms_txt: cannot resolve link target {target!r} in {page.file.src_uri}")
        # Pages without a markdown rendition (the api.md stub) link to their HTML instead.
        url = _md_uri(linked) if linked.src_uri in _state.rendition_uris else linked.url
        return f"{opening}{site_url}{url}{anchor or ''}{title or ''}{closing}"

    _state.page_markdown[page.file.src_uri] = _MD_LINK.sub(rewrite, resolved)
    return None


def _section_pages(section: Section) -> list[Page]:
    pages: list[Page] = []
    for child in section.children:
        if isinstance(child, Page) and child.file.src_uri in _state.rendition_uris:
            pages.append(child)
        elif isinstance(child, Section):
            pages.extend(_section_pages(child))
    return pages


def on_post_build(config: MkDocsConfig) -> None:
    assert _state.nav is not None and _state.files is not None
    missing = _state.rendition_uris - _state.page_markdown.keys()
    if missing:
        raise PluginError(f"llms_txt: pages skipped this build (is this a --dirty build?): {sorted(missing)}")

    site_dir = Path(config.site_dir)
    site_url = _site_url(config)

    top_level = [
        item for item in _state.nav.items if isinstance(item, Page) and item.file.src_uri in _state.rendition_uris
    ]
    sections: list[tuple[str, list[Page]]] = [("Docs", top_level)] if top_level else []
    for item in _state.nav.items:
        if isinstance(item, Section):
            pages = _section_pages(item)
            if pages:
                sections.append((item.title, pages))

    index = [f"# {config.site_name}", "", f"> {config.site_description}", ""]
    full: list[str] = []
    for title, pages in sections:
        index += [f"## {title}", ""]
        for page in pages:
            markdown = _state.page_markdown[page.file.src_uri]
            (site_dir / _md_uri(page.file)).write_text(markdown, encoding="utf-8")

            description = page.meta.get("description")
            tail = f": {description}" if description else ""
            index.append(f"- [{page.title}]({site_url}{_md_uri(page.file)}){tail}")

            body, h1_found = re.subn(r"\A\s*# .+\n", "", markdown)
            if not h1_found:
                raise PluginError(f"llms_txt: page {page.file.src_uri} does not start with an H1")
            full += [f"# {page.title}", "", f"Source: {page.canonical_url}", "", body.strip(), ""]
        index.append("")

    index += ["## Optional", ""]
    for src_uri, title, description in _OPTIONAL_PAGES:
        linked = _state.files.get_file_from_path(src_uri)
        if linked is None:
            raise PluginError(f"llms_txt: optional page {src_uri} not found")
        index.append(f"- [{title}]({site_url}{linked.url}): {description}")
    index.append("")

    (site_dir / "llms.txt").write_text("\n".join(index), encoding="utf-8")
    (site_dir / "llms-full.txt").write_text("\n".join(full), encoding="utf-8")
