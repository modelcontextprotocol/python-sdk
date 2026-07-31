"""Assemble a language site's docs tree, its status banners and its API links.

A language site is the English tree — minus the API reference, which is one
English artifact shared by every site — with the language's translated pages
laid over it, so an untranslated page still exists (as English) and every
prose link still resolves. Two deterministic rewrites happen here on the
staged copy, never on the committed pages: each prose page gets a note that
tells the reader what they are looking at (machine-translated, possibly behind
the English, not translated yet, its translation being refreshed, or available
in English only — chosen from the page's status, never by the model, so the
disclosure cannot be dropped or reworded by a translation run), and each link a
page writes relative to itself into `api/` is pointed at the same page in the
English API reference. The note text is the per-language snippets under
`i18n/banners/`, falling back to the English snippet a language lacks.

A translation is only ever laid over the tree it fits. Its document links are
the English page's links at the moment it was translated, so once the English
tree renames or drops one of those targets — the English page's link edited
along with it — the translation is left as the one page still linking a page
that no longer exists, and a strict build aborts on it. Such a translation is
withdrawn: the English page is staged in its place, marked with the `stale`
note, until a translation run refreshes it. Staleness earns a banner, never a
broken build. A dead link the current English page also carries is the
English tree's own defect, caught by its own strict build, never a reason to
withdraw a translation for copying it faithfully.
"""

from __future__ import annotations

import posixpath
import shutil
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# The page-URL mapping is owned by the llms.txt generator, and the external
# link classifier by the nav walker; a banner's English link and an
# absolutised API link use the same rules the built sites do.
from llms_txt import page_url
from navigation import EXTERNAL

from i18n.config import ROOT, ConfigError, banner_path, pages_dir, staged_docs_dir
from i18n.markdown import FRONTMATTER, links, parse_headings, rewrite_link_targets

ENGLISH_URL_PLACEHOLDER = "{english_url}"
TRANSLATIONS_PAGE_PLACEHOLDER = "{translations_page_url}"
TRANSLATIONS_PAGE = "translations.md"
# The English API reference tree; language sites link into it rather than
# carrying a copy.
API_DIR = "api"

# What a page is when it reaches staging: a translation that is up to date, a
# translation the English or the prompt inputs have since moved past, a page
# not translated yet (English body), or a page deliberately kept in English
# only (`exclude_pages`).
StageStatus = Literal["current", "outdated", "missing", "excluded"]
# What a page is staged as: any of the above, or `stale` — a translation
# withdrawn because it links pages the tree no longer carries, so the English
# body stands in for it.
StagedAs = Literal["current", "outdated", "missing", "excluded", "stale"]

# The banner snippet(s) each kind of page carries, in order.
BANNERS: dict[StagedAs, tuple[str, ...]] = {
    "current": ("disclosure",),
    "outdated": ("disclosure", "outdated"),
    "missing": ("untranslated",),
    "excluded": ("english-only",),
    "stale": ("stale",),
}

# Why a page with a translation still reads in English: its links no longer
# resolve against the tree (the same wording `status` and `stage` report).
STALE_LINKS_REASON = "links broken by an English change — English shown until refreshed"

# The banner sits under the page title so the title stays the first thing on
# the page; a page's title is its first level-1 heading outside code.
_TITLE_LEVEL = 1


@dataclass(frozen=True)
class Withdrawn:
    """A translation kept off the site: `dead_links` are the pages its links reach for and the tree lacks."""

    page: str
    dead_links: tuple[str, ...]


@dataclass(frozen=True)
class StagedTree:
    """A language's staged docs tree and the translations withdrawn from it."""

    docs: Path
    withdrawn: list[Withdrawn] = field(default_factory=list[Withdrawn])


def stage_language(
    code: str,
    statuses: Mapping[str, StageStatus],
    *,
    english_site_url: str,
    root: Path = ROOT,
) -> StagedTree:
    """Build the staged docs tree for one language of repository `root` and return it.

    `statuses` covers every prose page in the nav (translatable and excluded);
    a translation is laid over the English page only when it is `current` or
    `outdated` and it links no page the English tree has since renamed or
    dropped, so neither a leftover file nor a stranded translation can publish
    an orphan or a dead link.

    Raises:
        ConfigError: The staging directory does not lie inside `root`'s build directory.
    """
    docs, translations = root / "docs", pages_dir(code, root / "i18n")
    target = _empty_target(code, root)
    shutil.copytree(docs, target, ignore=_not_staged)
    present = staged_paths(docs)
    withdrawn: list[Withdrawn] = []
    for page, status in statuses.items():
        destination = target / page
        english = body = destination.read_text(encoding="utf-8")
        staged: StagedAs = status
        if status in ("current", "outdated"):
            translated = (translations / page).read_text(encoding="utf-8")
            if dead := stale_document_links(translated, english, page, present):
                staged = "stale"
                withdrawn.append(Withdrawn(page, tuple(dead)))
            else:
                body = translated
        body = absolutise_api_links(body, page, english_site_url=english_site_url)
        banner = _banner(code, staged, page, english_site_url=english_site_url, i18n_dir=root / "i18n")
        destination.write_text(inject_banner(body, banner), encoding="utf-8")
    return StagedTree(target, withdrawn)


def _empty_target(code: str, root: Path) -> Path:
    """The language's staging directory, emptied — refusing to delete anything outside `root/.build/`.

    The path is always derived from `root` and the language code, so this
    guard is the proof, before any tree is removed, that a bad code (`../..`)
    can never turn the wipe on the repository itself.

    Raises:
        ConfigError: The derived directory escapes `root/.build/`.
    """
    target = staged_docs_dir(code, root)
    build = (root / ".build").resolve()
    if not target.resolve().is_relative_to(build):
        raise ConfigError(f"refusing to stage into {target}: it is not inside {build}")
    if target.exists():
        shutil.rmtree(target)
    return target


def _staged_name(name: str) -> bool:
    """Whether a docs entry belongs in a staged tree: not the English `api/` tree, not a dot-entry (theme files)."""
    return name != API_DIR and not name.startswith(".")


def _not_staged(directory: str, names: list[str]) -> set[str]:
    """`shutil.copytree` ignore hook: the entries `staged_paths` leaves out."""
    return {name for name in names if not _staged_name(name)}


def staged_paths(docs: Path) -> set[str]:
    """The docs-relative posix paths — files and directories — a language's staged tree carries.

    The tree is the English `docs/` minus the API reference and dot-entries,
    and a translation only ever replaces a page in place, so this set is
    settled before any page is laid over the tree: a translation's links can
    be judged against it from the English tree alone.
    """
    paths: set[str] = set()
    for path in docs.rglob("*"):
        relative = path.relative_to(docs)
        if all(_staged_name(part) for part in relative.parts):
            paths.add(relative.as_posix())
    return paths


def missing_document_links(text: str, page: str, present: Collection[str]) -> list[str]:
    """The docs paths `text`'s links (written on `page`) reach for that the staged tree lacks, once each.

    Only a relative target can go missing: an in-page anchor, an absolute or
    external URL, and a link into `api/` (rewritten to the English reference)
    never depend on the tree. A relative target must be a page, directory or
    asset the tree carries at the path it resolves to, its fragment ignored.
    """
    missing: list[str] = []
    for link in links(text):
        target = link.target
        path = target.partition("#")[0]
        if not path or target.startswith("/") or EXTERNAL.match(target):
            continue
        resolved = _resolve(page, path)
        if resolved != "." and not _is_api_path(resolved) and resolved not in present and resolved not in missing:
            missing.append(resolved)
    return missing


def stale_document_links(translated: str, english: str, page: str, present: Collection[str]) -> list[str]:
    """The pages `page`'s translation still links to that its current English page has moved on from.

    These are the translation's dead links minus the English page's own: a
    target the English tree renamed or dropped, whose link the English page
    has since updated while the translation was not. A dead link the English
    page also writes is not counted — the translation copied it, and the
    English site's strict build is what catches it.
    """
    english_dead = set(missing_document_links(english, page, present))
    return [path for path in missing_document_links(translated, page, present) if path not in english_dead]


def _resolve(page: str, path: str) -> str:
    """`path` as written on `page`, resolved to a docs-relative posix path."""
    return posixpath.normpath(posixpath.join(posixpath.dirname(page), path))


def _is_api_path(resolved: str) -> bool:
    """Whether a docs-relative path lies in the English API reference tree."""
    return resolved == API_DIR or resolved.startswith(f"{API_DIR}/")


def absolutise_api_links(text: str, page: str, *, english_site_url: str) -> str:
    """Point `page`'s relative links into `api/` at the English API reference.

    The reference is not staged into a language site, so a target that
    resolves under `api/` from the linking page's directory has no page here;
    it becomes the absolute URL of that page on the English site, fragment
    kept. Every other target — other prose pages, assets, in-page anchors,
    external URLs — is left as written.
    """
    return rewrite_link_targets(text, lambda target: _english_api_url(page, target, english_site_url) or target)


def _english_api_url(page: str, target: str, english_site_url: str) -> str | None:
    """The English site URL of `target` if, written on `page`, it points into `api/`; else None."""
    if not target or target.startswith(("#", "/")) or EXTERNAL.match(target):
        return None
    path, _, fragment = target.partition("#")
    resolved = _resolve(page, path)
    if not _is_api_path(resolved):
        return None
    # A page target maps to its directory URL like every built page; a
    # directory-style target keeps the trailing slash normpath drops.
    if resolved.endswith(".md"):
        url = page_url(resolved)
    else:
        url = f"{resolved.rstrip('/')}/" if path.endswith("/") else resolved
    anchor = f"#{fragment}" if fragment else ""
    return f"{english_site_url.rstrip('/')}/{url}{anchor}"


def _banner(code: str, status: StagedAs, page: str, *, english_site_url: str, i18n_dir: Path) -> str:
    """The filled-in banner block for one page of one language."""
    english_url = english_site_url.rstrip("/") + "/" + page_url(page)
    translations_page_url = posixpath.relpath(TRANSLATIONS_PAGE, posixpath.dirname(page) or ".")
    snippets: list[str] = []
    for kind in BANNERS[status]:
        text = banner_path(kind, code, i18n_dir).read_text(encoding="utf-8").rstrip("\n")
        text = text.replace(ENGLISH_URL_PLACEHOLDER, english_url)
        text = text.replace(TRANSLATIONS_PAGE_PLACEHOLDER, translations_page_url)
        snippets.append(text)
    return "\n\n".join(snippets)


def inject_banner(text: str, banner: str) -> str:
    """Place `banner` right after the page's H1, else after any front matter, else at the top."""
    lines = text.split("\n")
    if title := next((h for h in parse_headings(text) if h.level == _TITLE_LEVEL), None):
        return "\n".join([*lines[: title.line + 1], "", banner, *lines[title.line + 1 :]])
    # A title-less page: the front matter (if any) must stay the file's first bytes.
    if head := FRONTMATTER.match(text):
        return f"{head.group(0)}\n{banner}\n\n" + text[head.end() :].lstrip("\n")
    return f"{banner}\n\n{text}"
