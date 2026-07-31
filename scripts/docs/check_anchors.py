"""Require an explicit anchor on every prose heading; `--fix` pins them.

Every heading in the hand-written docs carries its own id in the source
(`## Ask with a resolver {#ask-with-a-resolver}`, attr_list syntax) instead
of leaving the theme to slugify the heading text. That decouples the anchor
from the wording — a heading can be reworded or translated without moving
the `#fragment` links that point at it, and the ids are one grep away in the
source rather than a property of a build. The compact `{#id}` spelling is the
one markdownlint's fragment check recognises as a custom anchor.

Default mode is the check: for every ATX heading under `docs/**/*.md` (the
generated `docs/api/` tree and dot-directories exempt) it fails on a heading
without a trailing `{#anchor}`, on an anchor id using characters outside
letters, digits, `_` and `-`, and on an anchor a page uses twice — the anchor
rules the translation validator also enforces, defined once in
`i18n.markdown` (`anchor_problems`). `--fix` appends `{#<slug>}` to
unanchored headings, slugifying and de-duplicating the way the theme's `toc`
extension does. `--fix --from-site <dir>` instead copies the ids the built
site rendered for those headings — the mode used to pin the existing corpus,
since it cannot move an anchor by construction.

Usage:
    python scripts/docs/check_anchors.py
    python scripts/docs/check_anchors.py --fix
    python scripts/docs/check_anchors.py --fix --from-site site
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

# The heading/anchor/fence parsing and the anchor rules are the one
# implementation shared with the translation tool (this directory is the
# import root of the docs tooling), so this check, the translation validator
# and the mechanical repairer can never disagree about what an anchor is, how
# it is escaped, or which anchors are wrong.
from i18n.markdown import (
    HEADING_ATTRS,
    AnchorProblem,
    MalformedAnchor,
    MissingAnchor,
    UnspacedAnchor,
    anchor_problems,
    anchor_source_form,
    parse_headings,
    unescape,
)

ROOT = Path(__file__).parent.parent.parent
DOCS = ROOT / "docs"

# Inline markup that is not part of the rendered heading text the theme
# slugifies: images vanish, links keep their label, raw tags are stripped,
# underscore emphasis loses its markers (asterisks vanish in the slug anyway),
# and backslash escapes yield their literal character.
_CODE_SPAN = re.compile(r"(?<!\\)(?P<ticks>`+)(?P<code>.+?)(?<!`)(?P=ticks)(?!`)")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[(?P<label>[^\]]*)\](?:\([^)]*\)|\[[^\]]*\])")
_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_UNDERSCORE_EM = re.compile(r"(?<!\w)(?P<mark>_{1,2})(?=\S)(?P<inner>.+?)(?<=\S)(?P=mark)(?!\w)")

_DEDUPE_SUFFIX = re.compile(r"^(.*)_([0-9]+)$")
_HEADING_TAG = re.compile(r"h[1-6]")


def _plain_text(heading_text: str) -> str:
    """Reduce inline markdown to the text the rendered heading would carry."""
    codes: list[str] = []

    def stash(match: re.Match[str]) -> str:
        codes.append(match["code"].strip())
        return f"\x00{len(codes) - 1}\x00"

    text = _CODE_SPAN.sub(stash, heading_text)
    text = _IMAGE.sub("", text)
    text = _LINK.sub(lambda m: m["label"], text)
    text = _TAG.sub("", text)
    text = _UNDERSCORE_EM.sub(lambda m: m["inner"], text)
    text = html.unescape(unescape(text))
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m[1])], text)


def slugify(heading_text: str) -> str:
    """The id the theme's `toc` extension derives from a heading's text."""
    value = unicodedata.normalize("NFKD", _plain_text(heading_text))
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def unique(anchor: str, used: set[str]) -> str:
    """De-duplicate `anchor` against `used` the way `toc` does: `id`, `id_1`, `id_2`, ..."""
    while anchor in used or not anchor:
        match = _DEDUPE_SUFFIX.match(anchor)
        anchor = f"{match[1]}_{int(match[2]) + 1}" if match else f"{anchor}_1"
    used.add(anchor)
    return anchor


class _HeadingIdParser(HTMLParser):
    """Collect the `(level, id)` of every heading inside a page's `<article>`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self.headings: list[tuple[int, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "article":
            self._depth += 1
        elif self._depth and _HEADING_TAG.fullmatch(tag):
            self.headings.append((int(tag[1]), dict(attrs).get("id")))

    def handle_endtag(self, tag: str) -> None:
        if tag == "article" and self._depth:
            self._depth -= 1


def rendered_ids(site_dir: Path, page: Path) -> list[tuple[int, str | None]]:
    """The heading levels and ids the built site rendered for prose `page`."""
    stem = page.relative_to(DOCS).with_suffix("")
    html_file = site_dir / (stem.parent if stem.name == "index" else stem) / "index.html"
    if not html_file.is_file():
        raise SystemExit(f"check_anchors: no rendered page for {_repo_path(page)} at {html_file} — build first")
    parser = _HeadingIdParser()
    parser.feed(html_file.read_text(encoding="utf-8"))
    return parser.headings


def prose_pages(docs: Path = DOCS) -> list[Path]:
    """Hand-written pages under `docs/`: the generated `api/` tree and dot-directories aside.

    Only the path *inside* `docs/` decides that: a checkout that itself lives
    under a dot-directory (a worktree) still has all its prose pages, and
    finding none at all means the docs tree is missing, never that it passed.

    Raises:
        SystemExit: There is no prose page under `docs`.
    """
    parts = ((page, page.relative_to(docs).parts) for page in docs.rglob("*.md"))
    pages = sorted(page for page, rel in parts if rel[0] != "api" and not any(p.startswith(".") for p in rel))
    if not pages:
        raise SystemExit(f"check_anchors: found no prose pages under {docs} — is the docs tree in place?")
    return pages


def _repo_path(path: Path, *, root: Path = ROOT) -> str:
    """`path` as a repository-relative posix path, so messages read the same on every platform."""
    return path.relative_to(root).as_posix()


def check_pages(pages: list[Path], *, docs: Path = DOCS) -> tuple[int, list[str]]:
    """The heading count and every problem found: unanchored, malformed, glued and reused anchors.

    Problems name the page relative to the directory holding `docs`, so they
    read as repository paths (`docs/handlers/context.md:14: ...`).
    """
    total = 0
    problems: list[str] = []
    for page in pages:
        rel = _repo_path(page, root=docs.parent)
        headings = parse_headings(page.read_text(encoding="utf-8"))
        total += len(headings)
        problems += [f"{rel}:{problem.heading.line + 1}: {_describe(problem)}" for problem in anchor_problems(headings)]
    return total, problems


def _describe(problem: AnchorProblem) -> str:
    """One shared anchor problem, worded for a source page (the heading text or id, an earlier line)."""
    if isinstance(problem, MissingAnchor):
        return f"heading has no {{#anchor}}: {problem.heading.text!r}"
    if isinstance(problem, MalformedAnchor):
        return f'#{problem.heading.anchor} may only use letters, digits, "_", "-"'
    if isinstance(problem, UnspacedAnchor):
        return f"{{#{problem.heading.anchor}}} must follow a space, or the block renders as heading text"
    return f"#{problem.heading.anchor} already anchors line {problem.first.line + 1}"


def _pin(page: Path, site_dir: Path | None) -> int:
    """Append `{#id}` to each unanchored heading of `page`; returns how many were pinned."""
    lines = page.read_text(encoding="utf-8").split("\n")
    headings = parse_headings("\n".join(lines))
    if all(heading.anchor is not None for heading in headings):
        return 0
    rendered = rendered_ids(site_dir, page) if site_dir is not None else None
    if rendered is not None and [h.level for h in headings] != [level for level, _ in rendered]:
        raise SystemExit(
            f"check_anchors: rendered headings of {_repo_path(page)} don't line up with its source"
            " — rebuild the site from this tree before pinning from it"
        )
    used: set[str] = {heading.anchor for heading in headings if heading.anchor}
    pinned = 0
    for index, heading in enumerate(headings):
        if heading.anchor is not None:
            continue
        if rendered is not None:
            anchor = rendered[index][1]
            if not anchor:
                raise SystemExit(f"check_anchors: rendered heading at {_repo_path(page)}:{heading.line + 1} has no id")
        else:
            anchor = unique(slugify(heading.text), used)
        line = lines[heading.line].rstrip()
        attrs = HEADING_ATTRS.search(line)
        # A heading may already carry classes/attributes (`{ .cls }`) without an id.
        lines[heading.line] = (
            f"{line[: attrs.start('body')]}#{anchor_source_form(anchor)} {attrs['body']}{line[attrs.end('body') :]}"
            if attrs
            else f"{line} {{#{anchor_source_form(anchor)}}}"
        )
        pinned += 1
    if pinned:
        page.write_text("\n".join(lines), encoding="utf-8")
    return pinned


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fix", action="store_true", help="Append an anchor to every heading that lacks one.")
    parser.add_argument(
        "--from-site",
        metavar="SITE_DIR",
        type=Path,
        help="With --fix, pin the ids the built site rendered instead of computing slugs.",
    )
    args = parser.parse_args()
    if args.from_site and not args.fix:
        parser.error("--from-site only makes sense with --fix")

    pages = prose_pages()
    if args.fix:
        pinned = sum(_pin(page, args.from_site) for page in pages)
        print(f"check_anchors: pinned {pinned} heading anchors")
    total, problems = check_pages(pages)
    if problems:
        print("error: every prose heading needs an explicit anchor (run with --fix):", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit(1)
    print(f"check_anchors: {total} headings across {len(pages)} pages all carry anchors")


if __name__ == "__main__":
    main()
