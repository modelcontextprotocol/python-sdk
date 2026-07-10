"""Generate llms.txt, llms-full.txt, and per-page markdown (https://llmstxt.org/).

Zensical has no equivalent of MkDocs' build hooks, so this runs as a standalone
post-build step over the source tree (`mkdocs.yml` + `docs/`) and writes
three kinds of artifact into the built `site/`:

- `llms.txt`: a markdown index of the documentation, one link per page,
  grouped by nav section.
- a `.md` rendition of every prose page next to its HTML (e.g.
  `servers/tools/index.md`), which is what the llms.txt links point at.
- `llms-full.txt`: every prose page concatenated for single-fetch consumption.

Page markdown is the source markdown with YAML frontmatter stripped, `--8<--`
snippet includes resolved (so the `docs_src/` code examples appear inline) and
relative links rewritten to absolute URLs. The API reference pages under
`api/` are mkdocstrings stubs with no prose source, so they are linked as
rendered HTML from an Optional section instead of being embedded.

Usage:
    python scripts/docs/llms_txt.py --site-dir site
"""

from __future__ import annotations

import argparse
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Any

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
# Every markdown link/image target: `](target#anchor "title")`. Each target is
# classified in `_rewrite_links` — there is deliberately no shape-based
# pre-filter here, so no link can dodge validation by its spelling. Zensical's
# own link validation only covers .md targets (a missing image or
# directory-style link builds green even under --strict; MkDocs failed the
# build), so everything else is validated here.
_LINK = re.compile(r'(\]\([ \t]*)([^)\s]+?)(#[^)\s]*)?( +(?:"[^"]*"|\'[^\']*\'|\([^()]*\)))?([ \t]*\))')
# CommonMark forms the classifier deliberately rejects rather than models:
# angle-bracket destinations `](<target>)` and reference-style definitions
# `[label]: target` (footnote definitions `[^label]:` are a different,
# supported syntax). Either would otherwise dodge validation by its spelling;
# failing loud keeps the guarantee without modelling unused syntax.
_ANGLE_LINK = re.compile(r"\]\([ \t]*<")
_REF_DEFINITION = re.compile(r"^[ \t]*\[(?!\^)[^\]]+\]:", flags=re.MULTILINE)
# Block HTML comments are inert in rendered output: python-markdown passes
# them through verbatim, so commented-out prose must not be validated.
_HTML_COMMENT = re.compile(r"<!--.*?-->", flags=re.DOTALL)
# A scheme-prefixed target (https:, mailto:, tel:, ...) is external — the
# `://` shorthand misses scheme-only URIs like mailto:.
_EXTERNAL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")
# Fenced code blocks and inline code spans: their content is inert in the
# rendered HTML, so links inside them are illustrative text, neither validated
# nor rewritten. Fences are matched line-based in `_code_intervals` (closer at
# least as long as the opener, unclosed runs to EOF, per CommonMark) and spans
# only in the text between fences; a span cannot cross a blank line, so a
# stray unpaired backtick cannot swallow the paragraphs (and links) after it.
# Known approximations of the renderer's block model: 4-space-indented
# content is treated as prose, because in this corpus indentation is
# admonition/list body whose links must stay validated — a link in a true
# indented code block is over-validated (fails loud or gets rewritten in the
# rendition), never under-validated; and span pairing is bounded by blank
# lines rather than full block structure.
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(?s)(?<!`)(`+)(?!`)((?:(?!\n[ \t]*\n).)+?)(?<!`)\1(?!`)")
# A leading YAML frontmatter block, as MkDocs/Zensical parse it (mkdocs.utils.meta).
_FRONTMATTER = re.compile(r"\A---[ \t]*\n(?P<block>.*?)^(?:---|\.\.\.)[ \t]*(?:\n|\Z)", flags=re.MULTILINE | re.DOTALL)


class _BuildError(Exception):
    """A recoverable problem that should fail the docs build with a clear message."""


def _dest_md_uri(src_uri: str) -> str:
    """Map a source page (`servers/tools.md`) to its built rendition (`servers/tools/index.md`)."""
    path = PurePosixPath(src_uri)
    directory = path.parent if path.stem == "index" else path.parent / path.stem
    return "index.md" if directory == PurePosixPath(".") else f"{directory}/index.md"


def _page_url(src_uri: str) -> str:
    """The directory URL of a page relative to the site root (`servers/tools/`, `""` for the home page)."""
    return _dest_md_uri(src_uri).removesuffix("index.md")


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a leading YAML frontmatter block from a page (mirrors mkdocs.utils.meta).

    Hand-rolled deliberately: mkdocs is only a transitive dependency of this
    toolchain, so the pipeline must not import it. The hook this replaced ran
    post-frontmatter-extraction, so renditions never contained frontmatter and
    `meta` fed the page title and llms.txt description. A leading block that
    isn't a YAML mapping is page content, not frontmatter; an empty block is
    frontmatter with no meta.
    """
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text
    try:
        meta = yaml.safe_load(match["block"])
    except yaml.YAMLError:
        return {}, text
    if meta is not None and not isinstance(meta, dict):
        return {}, text
    return meta or {}, text[match.end() :].lstrip("\n")


def _collect_pages(items: list, prose: dict[str, str | None]) -> list[str]:
    """Collect the prose pages under a nav subtree, in nav order.

    Records each page in `prose` (src_uri -> nav title, or `None` to fall
    back to the page's H1). This is the single owner of the prose-page rule:
    a page entry counts when it is a local .md path (external URLs render as
    outbound nav links and are omitted, as the MkDocs pipeline did) and is not
    part of the generated API reference.
    """
    pages: list[str] = []
    for entry in items:
        title, value = next(iter(entry.items())) if isinstance(entry, dict) else (None, entry)
        if isinstance(value, list):
            pages.extend(_collect_pages(value, prose))
        elif not _EXTERNAL.match(value) and value.endswith(".md") and not value.startswith("api/"):
            # Contained values only: an escaping entry would write its
            # rendition outside the built site.
            if value.startswith("/") or posixpath.normpath(value).startswith(".."):
                raise _BuildError(f"llms_txt: nav entry {value!r} escapes docs/")
            prose[value] = title
            pages.append(value)
    return pages


def _walk_nav(nav: list, prose: dict[str, str | None], sections: list[tuple[str, list[str]]]) -> list[str]:
    """Split the nav into a flat list of top-level pages and titled sections.

    Populates `sections` ((title, [src_uri]) in nav order) and returns the
    top-level page src_uris; page collection itself is `_collect_pages`.
    """
    top_level: list[str] = []
    for entry in nav:
        title, value = next(iter(entry.items())) if isinstance(entry, dict) else (None, entry)
        if isinstance(value, list):
            pages = _collect_pages(value, prose)
            if pages:
                assert title is not None
                sections.append((title, pages))
        else:
            top_level.extend(_collect_pages([entry], prose))
    return top_level


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


def _in_code(code: list[tuple[int, int]], position: int) -> bool:
    """Whether `position` falls inside any code interval."""
    return any(start <= position < end for start, end in code)


def _prose_h1(markdown: str) -> re.Match[str] | None:
    """The first ATX H1 outside code (at most 3 spaces of indent, per CommonMark).

    Code-awareness matters: every resolved `.py` snippet starts with a
    `# path` pointer line that must never win over the page's real H1.
    """
    code = _code_intervals(markdown)
    for match in re.finditer(r"^ {0,3}# (.+)$", markdown, flags=re.MULTILINE):
        if not _in_code(code, match.start()):
            return match
    return None


def _code_intervals(markdown: str) -> list[tuple[int, int]]:
    """The character spans of fenced code blocks and inline code spans."""
    fences: list[tuple[int, int]] = []
    opener = ""
    start = offset = 0
    for line in markdown.splitlines(keepends=True):
        if not opener:
            if match := _FENCE.match(line):
                opener, start = match[1], offset
        elif (stripped := line.strip()).startswith(opener) and set(stripped) == {opener[0]}:
            fences.append((start, offset + len(line)))
            opener = ""
        offset += len(line)
    if opener:
        fences.append((start, len(markdown)))

    intervals = list(fences)
    previous_end = 0
    for fence_start, fence_end in [*fences, (len(markdown), len(markdown))]:
        segment = markdown[previous_end:fence_start]
        for pattern in (_CODE_SPAN, _HTML_COMMENT):
            intervals += [(previous_end + m.start(), previous_end + m.end()) for m in pattern.finditer(segment)]
        previous_end = fence_end
    return intervals


def _rewrite_links(markdown: str, src_uri: str, site_url: str, prose: dict[str, str | None]) -> str:
    src_dir = posixpath.dirname(src_uri)
    code = _code_intervals(markdown)

    rejected = ((_ANGLE_LINK, "angle-bracket link destination"), (_REF_DEFINITION, "reference-style link definition"))
    for pattern, form in rejected:
        for match in pattern.finditer(markdown):
            if not _in_code(code, match.start()):
                raise _BuildError(f"llms_txt: {form} in {src_uri} is not supported here; use a plain inline link")

    def rewrite(match: re.Match[str]) -> str:
        opening, target, anchor, title, closing = match.groups()
        if target.startswith("#") or _EXTERNAL.match(target):
            return match.group(0)  # in-page anchor or external URL (https:, mailto:, ...)
        if _in_code(code, match.start()):
            return match.group(0)  # illustrative link inside a code block/span
        if target.startswith("/"):
            raise _BuildError(f"llms_txt: absolute link target {target!r} in {src_uri}: link the .md source instead")
        linked = posixpath.normpath(posixpath.join(src_dir, target))
        if linked == ".." or linked.startswith("../"):
            raise _BuildError(f"llms_txt: link target {target!r} in {src_uri} escapes docs/")
        if (DOCS / linked).is_dir():
            raise _BuildError(
                f"llms_txt: directory-style link target {target!r} in {src_uri}: link the page's .md source instead"
            )
        if not (DOCS / linked).is_file():
            raise _BuildError(f"llms_txt: cannot resolve link target {target!r} in {src_uri}")
        if linked.endswith(".md"):
            # Pages without a markdown rendition (the api/ stubs) link to their HTML instead.
            url = _dest_md_uri(linked) if linked in prose else _page_url(linked)
        else:
            url = linked  # assets are published at their docs-relative path
        return f"{opening}{site_url}{url}{anchor or ''}{title or ''}{closing}"

    return _LINK.sub(rewrite, markdown)


def _title(src_uri: str, nav_title: str | None, meta: dict[str, Any], body: str) -> str:
    if nav_title is not None:
        return nav_title
    if isinstance(meta_title := meta.get("title"), str):
        return meta_title
    if match := _prose_h1(body):
        return match.group(1).strip()
    raise _BuildError(f"llms_txt: page {src_uri} has no nav title, no title frontmatter, and no H1")


def generate(site_dir: Path) -> None:
    if not (DOCS / "api").is_dir():
        raise _BuildError("llms_txt: docs/api not found (run gen_ref_pages first)")

    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    site_url = config["site_url"].rstrip("/") + "/"

    prose: dict[str, str | None] = {}
    sections: list[tuple[str, list[str]]] = []
    top_level = _walk_nav(config["nav"], prose, sections)
    ordered: list[tuple[str, list[str]]] = ([("Docs", top_level)] if top_level else []) + sections

    rendered: dict[str, str] = {}
    metas: dict[str, dict[str, Any]] = {}
    for src_uri in prose:
        metas[src_uri], markdown = _split_frontmatter((DOCS / src_uri).read_text(encoding="utf-8"))
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

            title = _title(src_uri, prose[src_uri], metas[src_uri], markdown)
            description = metas[src_uri].get("description")
            tail = f": {description}" if description else ""
            index.append(f"- [{title}]({site_url}{md_uri}){tail}")

            # `full` re-titles every page, so drop its first prose H1 (the
            # same one `_title` falls back to).
            h1 = _prose_h1(markdown)
            body = markdown if h1 is None else markdown[: h1.start()] + markdown[h1.end() :]
            full += [f"# {title}", "", f"Source: {site_url}{_page_url(src_uri)}", "", body.strip(), ""]
        index.append("")

    index += ["## Optional", ""]
    # _OPTIONAL_PAGES must match the generated package indexes exactly: a
    # package added to gen_ref_pages.PACKAGES without an entry here would be
    # published on the site but silently missing from llms.txt, and a stale
    # entry would link a page that no longer exists.
    generated = {f"api/{path.name}/index.md" for path in (DOCS / "api").iterdir() if path.is_dir()}
    listed = {src_uri for src_uri, _, _ in _OPTIONAL_PAGES}
    if generated != listed:
        raise _BuildError(
            f"llms_txt: _OPTIONAL_PAGES out of sync with docs/api:"
            f" missing {sorted(generated - listed)}, stale {sorted(listed - generated)}"
        )
    for src_uri, title, description in _OPTIONAL_PAGES:
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
    except OSError as exc:
        raise SystemExit(f"llms_txt: {exc}") from exc


if __name__ == "__main__":
    main()
