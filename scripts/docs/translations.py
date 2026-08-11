"""Machine-translate the documentation and stage each language site for the build.

English under `docs/` is the source of truth. Every language in
`i18n/languages.yml` gets generated pages under `i18n/<code>/pages/`, driven by
that language's hand-written `instructions.md` and `glossary.json` plus the
shared `i18n/general-prompt.md`. Corrections go into those inputs, never into
the generated pages. Each generated page records, in its own front matter, the
English section hashes it reflects; nothing else tracks state.

Usage (from the repository root):
    python scripts/docs/translations.py status [--lang CODE]
    python scripts/docs/translations.py translate --lang CODE [--pages PATH ... | --grep RE] [--limit N] [--dry-run]
    python scripts/docs/translations.py stage --lang CODE

Only `translate` without `--dry-run` calls the model (credentials come from
the environment, e.g. `ANTHROPIC_API_KEY`) and needs the `translate`
dependency group. `DOCS_TRANSLATE_MODEL`, if set, replaces the registry's
`model` for that run, to trial another model without editing the registry.
Exit codes: 0 done, 1 some page failed, 2 configuration or credential error,
3 internal error (nothing the run wrote should be proposed).
"""

import argparse
import hashlib
import importlib
import json
import os
import posixpath
import re
import shutil
import sys
import traceback
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import markdown
import yaml
import zensical.config
from build_config import ROOT, Language, Registry, load_registry, nav_page_paths, staged_docs_dir, staged_titles_file
from llms_txt import page_url
from zensical.config import ConfigurationError

# Zensical annotates its config loader `-> dict`; this is the shape its own renderer relies on.
parse_mkdocs_config = cast("Callable[[str], dict[str, Any]]", getattr(zensical.config, "parse_mkdocs_config"))

# Bumped only when the generated-file contract changes; older files then read as missing.
TOOL_VERSION = 1
# `max_tokens` per request: several times the longest page, leaving room for
# any thinking the model does (it counts against the same budget), while still
# inside the output ceiling streaming requests allow.
OUTPUT_TOKEN_BUDGET = 64_000
# Repair turns fed back to the model after the first reply before a page fails.
MAX_REPAIRS = 2
DEFAULT_LIMIT = 15
NOTICES_PAGE = "i18n/notices.md"
NOTICE_KINDS = ("translated", "outdated", "english")
API_DIR = "api"

Status = Literal["missing", "outdated", "current"]
NoticeKind = Literal["translated", "outdated", "english"]


class ConfigError(Exception):
    """Unusable configuration, inputs or credentials (exit code 2)."""


class PageError(Exception):
    """One page cannot be translated or overlaid; the run continues with the next page."""


# ---- Markdown structure: front matter, fences, headings, code spans, links ----

FRONT_MATTER = re.compile(r"\A---[ \t]*\n(?P<body>.*?)^(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.MULTILINE | re.DOTALL)
# An ATX heading the way the renderer reads it: hashes at column 0, no space
# required after them, an optional closing hash run, backslash escapes honoured.
HEADING = re.compile(r"^(?P<hashes>#{1,6})(?!#)(?P<text>(?:\\.|[^\\\n])*?)#*[ \t]*$")
# A heading's trailing attr_list block(s), matched with or without the whitespace
# attr_list itself needs, so blocks the model glued to CJK text or doubled are
# still seen; `body` is the last block's, the one attr_list reads.
HEADING_ATTRS = re.compile(r"(?:[ \t]*\{:?[ \t]*(?P<body>[^}\n]*?)[ \t]*\})+[ \t]*$")
ESCAPE = re.compile(r"\\(?P<char>[!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])")
# An underscore that is not word-internal turns into emphasis before attr_list
# reads the block, so it must be written escaped inside `{#...}`.
_BOUNDARY_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])")
_FENCE = re.compile(r"^[ \t]*(?P<run>`{3,}|~{3,})(?P<info>[^\n]*)$")
# Cannot cross a blank line, so a stray backtick cannot swallow later paragraphs.
CODE_SPAN = re.compile(r"(?s)(?<!`)(`+)(?!`)((?:(?!\n[ \t]*\n).)+?)(?<!`)\1(?!`)")
LINK = re.compile(r"(?P<image>!?)\[(?P<label>[^\]]*)\]\((?P<target>[^)\s]*)(?P<title>[^)]*)\)")
_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://(?:(?![<>)\]])[!-~])+")
_TAG = re.compile(r"</?[A-Za-z][^>\n]*>|<!--.*?-->", re.DOTALL)
EXTERNAL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")
_MARKER = re.compile(r"^[ \t]*(?P<marker>!!!|\?\?\?\+?|===)[ \t]+(?P<kind>[\w-]+)?")
_TABLE_ROW = re.compile(r"^[ \t]*\|")
_SNIPPET = re.compile(r'^[ \t]*-+8<-+[ \t]+"(?P<path>[^"\n]+)"[ \t]*$', re.MULTILINE)
_WRAPPER = re.compile(
    r"\A[ \t]*\n*(?P<open>`{3,}|~{3,})[^\n]*\n(?P<body>.*)\n(?P<close>`{3,}|~{3,})[ \t]*\n*\Z", re.DOTALL
)
# Bracketed text followed by `(` or `[` is a link label, never a placeholder.
_PLACEHOLDERS = (
    re.compile(r"\[\s*(?:translation|rest of|remaining)[^\]]*\](?![(\[])", re.IGNORECASE),
    re.compile(r"\((?:content )?omitted[^)]*\)", re.IGNORECASE),
    re.compile(r"\[\s*\.\.\.\s*\](?![(\[])"),
)
_COMMENT = re.compile(r"<!--(?P<body>.*?)-->", re.DOTALL)
_ABRIDGED = re.compile(r"\b(?:omitted|continues|truncated|abridged|remaining|rest of)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Heading:
    """One ATX heading; `text` excludes any trailing `{...}` attr block."""

    line: int
    level: int
    text: str
    anchor: str | None


@dataclass(frozen=True)
class FenceLines:
    """Line indices of one fenced block; an unclosed fence runs to the last line."""

    opener: int
    closer: int
    closed: bool


@dataclass(frozen=True)
class LinkRef:
    """A markdown link or image in prose: the whole match and its target, as character spans."""

    start: int
    end: int
    target_start: int
    target_end: int
    label: str
    target: str


def split_front_matter(text: str) -> tuple[str | None, str]:
    """`(front matter YAML, body)`; the YAML is None when the page has no front matter block."""
    match = FRONT_MATTER.match(text)
    return (match["body"], text[match.end() :]) if match else (None, text)


def fence_ranges(lines: Sequence[str]) -> list[FenceLines]:
    """The fenced blocks of `lines`, in order (CommonMark opener/closer rules)."""
    found: list[FenceLines] = []
    opener: re.Match[str] | None = None
    start = 0
    for index, line in enumerate(lines):
        match = _FENCE.match(line)
        if opener is None:
            if match and not (match["run"][0] == "`" and "`" in match["info"]):
                opener, start = match, index
            continue
        run = opener["run"]
        if match and match["run"][0] == run[0] and len(match["run"]) >= len(run) and not match["info"].strip():
            found.append(FenceLines(start, index, closed=True))
            opener = None
    if opener is not None:
        found.append(FenceLines(start, len(lines) - 1, closed=False))
    return found


def _prose_lines(text: str) -> list[str]:
    """The lines with fenced-block bodies blanked, so structure scans never read code."""
    lines = text.split("\n")
    for fence in fence_ranges(lines):
        for index in range(fence.opener + 1, fence.closer if fence.closed else fence.closer + 1):
            lines[index] = ""
    return lines


def parse_headings(text: str) -> list[Heading]:
    """The ATX headings of `text` in order, with the id any trailing `{#...}` block pins."""
    found: list[Heading] = []
    for index, line in enumerate(_prose_lines(text)):
        if not (match := HEADING.match(line)):
            continue
        heading, anchor = match["text"].strip(), None
        if attrs := HEADING_ATTRS.search(heading):
            ids = [token[1:] for token in attrs["body"].split() if token.startswith("#") and len(token) > 1]
            anchor = ESCAPE.sub(r"\g<char>", ids[-1]) if ids else None
            heading = heading[: attrs.start()].rstrip()
        found.append(Heading(index, len(match["hashes"]), heading, anchor))
    return found


def anchor_source_form(anchor: str) -> str:
    """The rendered id as it must be written inside `{#...}` to survive the emphasis pass."""
    return _BOUNDARY_UNDERSCORE.sub(r"\\_", anchor)


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace each span with same-length spaces, keeping newlines so positions and lines survive."""
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def _mask_fences(text: str) -> str:
    """Blank every fenced block, marker lines included (same length, same lines)."""
    lines = text.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    return _blank(text, [(offsets[fence.opener], offsets[fence.closer + 1] - 1) for fence in fence_ranges(lines)])


def mask_code(text: str) -> str:
    """Blank fenced blocks and inline code spans (same length, same lines)."""
    masked = _mask_fences(text)
    return _blank(masked, [match.span() for match in CODE_SPAN.finditer(masked)])


def mask(text: str) -> str:
    """Blank everything that is not translatable prose: code, link targets, bare URLs, HTML tags."""
    masked = mask_code(text)
    spans = [match.span("target") for match in LINK.finditer(masked)]
    spans += [match.span() for pattern in (_URL, _TAG) for match in pattern.finditer(masked)]
    return _blank(masked, spans)


def code_spans(text: str) -> Counter[str]:
    """The inline code spans of the prose (fenced code excluded), counted by content."""
    return Counter(match.group(2).strip() for match in CODE_SPAN.finditer(_mask_fences(text)))


def links(text: str) -> list[LinkRef]:
    """The markdown links and images written in the prose of `text` (code is masked for detection only)."""
    return [
        LinkRef(
            m.start(), m.end(), m.start("target"), m.end("target"), text[m.start("label") : m.end("label")], m["target"]
        )
        for m in LINK.finditer(mask_code(text))
    ]


def is_relative(target: str) -> bool:
    """Whether a link target depends on the docs tree (not a URL, not site-absolute)."""
    return not EXTERNAL.match(target) and not target.startswith("/")


def _replace_spans(text: str, edits: list[tuple[int, int, str]]) -> str:
    parts: list[str] = []
    cursor = 0
    for start, end, replacement in sorted(edits):
        parts += [text[cursor:start], replacement]
        cursor = end
    return "".join([*parts, text[cursor:]])


def markers(text: str) -> list[str]:
    """The admonition (`!!!`/`???`) markers with their type keyword, and the tab (`===`) markers, in order."""
    matches = [match for line in _prose_lines(text) if (match := _MARKER.match(line))]
    return ["===" if match["marker"] == "===" else f"{match['marker']} {match['kind'] or '?'}" for match in matches]


def table_rows(text: str) -> list[int]:
    """The row count of each table (a run of consecutive `|` lines), in order."""
    counts: list[int] = []
    run = 0
    for line in [*_prose_lines(text), ""]:
        if _TABLE_ROW.match(line):
            run += 1
        elif run:
            counts.append(run)
            run = 0
    return counts


def abridgements(text: str) -> Counter[str]:
    """Placeholder phrases and "omitted" comments of the kind a model leaves where it cut a page short."""
    prose = mask(text)
    found = [match.group(0) for pattern in _PLACEHOLDERS for match in pattern.finditer(prose)]
    found += [c.group(0) for c in _COMMENT.finditer(mask_code(text)) if _ABRIDGED.search(c["body"])]
    return Counter(found)


# ---- Sections, hashes and the provenance front matter of a generated page ----


def sections(body: str) -> list[str]:
    """The page as intro + one string per `##` section; `"".join(sections(body)) == body`.

    Blank lines just above a `##` heading belong to that heading's section, so
    a section's bytes never depend on the section after it.
    """
    lines = body.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    starts = [0]
    for heading in parse_headings(body):
        if heading.level != 2:
            continue
        first = heading.line
        while first > 0 and not lines[first - 1].strip():
            first -= 1
        starts.append(offsets[first])
    return [body[start:end] for start, end in zip(starts, [*starts[1:], len(body)])]


def section_label(section: str, index: int) -> str:
    """How a section is named in prompts and status lines."""
    if index == 0:
        return "the introduction (everything before the first `##` heading)"
    return section.strip("\n").split("\n", 1)[0].strip()


def digest(text: str) -> str:
    """The first 16 hex digits of the text's sha256."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def section_hashes(body: str) -> list[str]:
    return [digest(section) for section in sections(body)]


@dataclass(frozen=True)
class Provenance:
    """What a generated page was made from, carried in its front matter (deliberately not the model)."""

    sections: tuple[str, ...]
    inputs: str


def with_provenance(body: str, provenance: Provenance) -> str:
    """The generated file: provenance front matter, then the translated body."""
    record = {"translation": {"sections": list(provenance.sections), "inputs": provenance.inputs, "tool": TOOL_VERSION}}
    header = yaml.safe_dump(record, sort_keys=False, default_flow_style=None, width=2**16, allow_unicode=True)
    return f"---\n{header}---\n{body}"


def read_provenance(front_matter: str | None) -> Provenance | None:
    """The provenance recorded in a generated page's front matter, or None if absent or off-schema."""
    if front_matter is None:
        return None
    try:
        loaded: object = yaml.safe_load(front_matter)
    except yaml.YAMLError:
        return None
    record: object = cast("dict[str, object]", loaded).get("translation") if isinstance(loaded, dict) else None
    if not isinstance(record, dict):
        return None
    fields = cast("dict[str, object]", record)
    hashes, inputs = fields.get("sections"), fields.get("inputs")
    if set(fields) != {"sections", "inputs", "tool"} or fields["tool"] != TOOL_VERSION:
        return None
    if not isinstance(hashes, list) or not all(isinstance(item, str) for item in cast("list[object]", hashes)):
        return None
    if not isinstance(inputs, str):
        return None
    return Provenance(tuple(cast("list[str]", hashes)), inputs)


# ---- The repository: registry, nav pages, prompt inputs and the renderer's heading ids ----


@dataclass(frozen=True)
class Term:
    source: str
    target: str
    note: str = ""
    avoid: tuple[str, ...] = ()


@dataclass(frozen=True)
class Glossary:
    keep: tuple[str, ...]
    terms: tuple[Term, ...]


def load_glossary(path: Path) -> Glossary:
    """Parse `glossary.json`; the schema is closed, so a misspelt key is an error.

    Raises:
        ConfigError: The file is missing, not JSON, or off-schema.
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    def strings(where: str, value: object) -> tuple[str, ...]:
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in cast("list[object]", value)):
            raise ConfigError(f"{path}: {where} must be a list of non-empty strings")
        return tuple(cast("list[str]", value))

    if not isinstance(raw, dict) or set(cast("dict[str, object]", raw)) != {"keep", "terms"}:
        raise ConfigError(f'{path}: top level must be an object with exactly the keys "keep" and "terms"')
    top = cast("dict[str, object]", raw)
    entries = top["terms"]
    if not isinstance(entries, list):
        raise ConfigError(f"{path}: terms must be a list")
    terms: list[Term] = []
    for index, entry in enumerate(cast("list[object]", entries)):
        where = f"terms[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: {where} must be an object")
        item = cast("dict[str, object]", entry)
        if unknown := sorted(set(item) - {"source", "target", "note", "avoid"}):
            raise ConfigError(f"{path}: {where} has unknown keys {unknown}")
        source, target, note = item.get("source"), item.get("target"), item.get("note", "")
        if not isinstance(source, str) or not isinstance(target, str) or not isinstance(note, str):
            raise ConfigError(f"{path}: {where} needs string source and target (note optional)")
        terms.append(Term(source, target, note, strings(f"{where}.avoid", item.get("avoid", []))))
    return Glossary(strings("keep", top["keep"]), tuple(terms))


@dataclass(frozen=True)
class Inputs:
    """One language's prompt inputs; `hash` fingerprints all of them (provenance only)."""

    language: Language
    general_prompt: str
    instructions: str
    glossary: Glossary
    hash: str


@dataclass(frozen=True)
class Page:
    """A translatable page: its display key, English source file and generated translation file."""

    key: str
    source: Path
    target: Path


@dataclass(frozen=True)
class Notice:
    title: str
    body: str


def parse_notices(body: str) -> dict[str, Notice]:
    """The `##` sections of a notices page keyed by their pinned id."""
    lines = body.split("\n")
    headings = [heading for heading in parse_headings(body) if heading.level == 2]
    found: dict[str, Notice] = {}
    for position, heading in enumerate(headings):
        end = headings[position + 1].line if position + 1 < len(headings) else len(lines)
        if heading.anchor:
            found[heading.anchor] = Notice(heading.text, "\n".join(lines[heading.line + 1 : end]).strip("\n"))
    return found


@dataclass
class Repo:
    """Everything the commands read from a checkout rooted at `root`."""

    root: Path
    registry: Registry
    prose_pages: list[str]
    translatable: list[str]
    notices: dict[str, Notice]
    renderer: markdown.Markdown

    @property
    def docs(self) -> Path:
        return self.root / "docs"

    @property
    def i18n(self) -> Path:
        return self.root / "i18n"

    def language(self, code: str) -> Language:
        for language in self.registry.languages:
            if language.code == code:
                return language
        known = ", ".join(language.code for language in self.registry.languages)
        raise ConfigError(f"unknown language {code!r} (i18n/languages.yml has: {known})")

    def inputs(self, language: Language) -> Inputs:
        texts: list[str] = []
        for path in (self.i18n / "general-prompt.md", self.i18n / language.code / "instructions.md"):
            try:
                texts.append(path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ConfigError(f"cannot read {path}: {exc}") from exc
        glossary_path = self.i18n / language.code / "glossary.json"
        glossary = load_glossary(glossary_path)
        fingerprint = digest("\0".join([*texts, glossary_path.read_text(encoding="utf-8")]))
        return Inputs(language, texts[0], texts[1], glossary, fingerprint)

    def pages(self, language: Language) -> list[Page]:
        """The language's translatable pages in nav order, then the notices page."""
        generated = self.i18n / language.code / "pages"
        pages = [Page(key, self.docs / key, generated / key) for key in self.translatable]
        return [*pages, Page(NOTICES_PAGE, self.root / NOTICES_PAGE, self.i18n / language.code / "notices.md")]

    def render_ids(self, body: str) -> list[str]:
        """The heading ids the site renderer gives a page body (no front matter), in document order."""
        self.renderer.reset()
        self.renderer.convert(body)
        tokens = cast("list[dict[str, Any]]", getattr(self.renderer, "toc_tokens", []))
        return [str(token["id"]) for token in _flatten(tokens)]

    def heading_ids(self, body: str) -> list[str]:
        """`render_ids`, checked to pair one-to-one with the source headings this tool can pin.

        Raises:
            PageError: The renderer sees headings the source scan does not (setext, indented, HTML).
        """
        ids, found = self.render_ids(body), parse_headings(body)
        if len(ids) != len(found):
            raise PageError(f"the page renders {len(ids)} headings but {len(found)} are ATX headings at column 0")
        return ids


def _flatten(tokens: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for token in tokens:
        yield token
        yield from _flatten(cast("list[dict[str, Any]]", token["children"]))


def _renderer(root: Path) -> markdown.Markdown:
    """A python-markdown instance configured with the extensions the site build uses."""
    try:
        config = parse_mkdocs_config(str(root / "mkdocs.yml"))
    except (OSError, yaml.YAMLError, ConfigurationError) as exc:
        raise ConfigError(f"cannot load {root / 'mkdocs.yml'}: {exc}") from exc
    configs = cast("dict[str, dict[str, Any]]", config["mdx_configs"])
    # Snippet paths resolve against the build's working directory, the
    # repository root. Only heading ids are read here, so a missing snippet is
    # not this renderer's failure (`plan` checks snippet paths itself).
    snippets = configs.setdefault("pymdownx.snippets", {})
    snippets["base_path"] = [str(root / base) for base in cast("list[str]", snippets.get("base_path", ["."]))]
    snippets["check_paths"] = False
    return markdown.Markdown(extensions=config["markdown_extensions"], extension_configs=configs)


def _excluded(page: str, patterns: Sequence[str]) -> bool:
    """`dir/**` excludes a subtree; any other pattern is an exact page path."""
    return any(page.startswith(p.removesuffix("**")) if p.endswith("/**") else page == p for p in patterns)


def read_english(path: Path) -> str:
    """An English page's body; any front matter is dropped here, once, so no later step ever sees it.

    Raises:
        ConfigError: The file cannot be read.
    """
    try:
        return split_front_matter(path.read_text(encoding="utf-8"))[1]
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc


def load_repo(root: Path) -> Repo:
    """Read the registry, the nav and the English notices of the checkout at `root`.

    Raises:
        ConfigError: Any of them is missing or malformed.
    """
    try:
        registry = load_registry(root)
        config: object = yaml.safe_load((root / "mkdocs.yml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, ValueError) as exc:  # build_config reports registry problems as ValueError
        raise ConfigError(str(exc)) from exc
    nav = cast("dict[str, Any]", config).get("nav") if isinstance(config, dict) else None
    if not isinstance(nav, list):
        raise ConfigError(f"{root / 'mkdocs.yml'}: no nav list")
    prose = [p for p in nav_page_paths(cast("list[Any]", nav)) if p.endswith(".md") and not p.startswith(f"{API_DIR}/")]
    notices = parse_notices(read_english(root / NOTICES_PAGE))
    if missing := [kind for kind in NOTICE_KINDS if kind not in notices]:
        raise ConfigError(f"{root / NOTICES_PAGE}: missing `## ... {{#id}}` sections for {missing}")
    translatable = [page for page in prose if not _excluded(page, registry.exclude)]
    return Repo(root, registry, prose, translatable, notices, _renderer(root))


# ---- Page status ----


@dataclass(frozen=True)
class Translation:
    """A generated page split into its provenance (None when unreadable) and body."""

    provenance: Provenance | None
    body: str


@dataclass(frozen=True)
class PageState:
    """One page classified against the current English text."""

    page: Page
    english: str
    hashes: list[str]
    translation: Translation | None
    status: Status
    changed: list[int] = field(default_factory=list[int])
    note: str = ""

    def predates(self, inputs: Inputs) -> bool:
        """Whether the translation was generated with earlier prompt inputs than these (informational)."""
        provenance = self.translation.provenance if self.translation else None
        return provenance is not None and provenance.inputs != inputs.hash


def read_translation(path: Path) -> Translation | None:
    if not path.is_file():
        return None
    front_matter, body = split_front_matter(path.read_text(encoding="utf-8"))
    return Translation(read_provenance(front_matter), body)


def classify(page: Page) -> PageState:
    """Compare the page's recorded section hashes with the current English ones.

    Raises:
        ConfigError: The English source cannot be read.
    """
    english = read_english(page.source)
    hashes = section_hashes(english)
    translation = read_translation(page.target)
    if translation is None:
        return PageState(page, english, hashes, None, "missing")
    if translation.provenance is None:
        return PageState(
            page, english, hashes, translation, "missing", note="unreadable front matter, retranslated whole"
        )
    recorded = translation.provenance.sections
    if tuple(hashes) == recorded:
        return PageState(page, english, hashes, translation, "current")
    changed = [index for index, value in enumerate(hashes) if value not in set(recorded)]
    labels = ", ".join(section_label(sections(english)[index], index) for index in changed)
    note = f"English changed in: {labels}" if changed else "English sections removed or reordered"
    return PageState(page, english, hashes, translation, "outdated", changed, note)


def removable(repo: Repo, language: Language) -> list[str]:
    """Generated pages whose English page left the translatable set (the fix is `git rm`)."""
    generated = repo.i18n / language.code / "pages"
    on_disk = sorted(path.relative_to(generated).as_posix() for path in generated.rglob("*.md"))
    return [page for page in on_disk if page not in set(repo.translatable)]


# ---- Prompts and the model client ----


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.cache_read_tokens += other.cache_read_tokens

    def __str__(self) -> str:
        return (
            f"{self.input_tokens} input / {self.output_tokens} output / "
            f"{self.cache_write_tokens} cache-write / {self.cache_read_tokens} cache-read tokens"
        )


@dataclass(frozen=True)
class Completion:
    text: str
    usage: Usage
    stop_reason: str | None = "end_turn"


class Translator(Protocol):
    """Anything that answers a conversation; tests inject a scripted fake."""

    def complete(self, *, model: str, system: str, messages: Sequence[Message], max_tokens: int) -> Completion:
        """Return the model's reply.

        Raises:
            ConfigError: The credentials were rejected.
            PageError: The request failed.
        """
        ...


def anthropic_translator() -> Translator:
    """The Claude Messages API client, streaming, with the system prompt as one cached block.

    `anthropic` (and `httpx`, its own dependency) lives in the non-default
    `translate` dependency group, so it is imported here, by name: offline
    commands and type checking never need it.

    Raises:
        ConfigError: The `translate` dependency group is not installed, or no credentials are configured.
    """
    try:
        sdk = importlib.import_module("anthropic")
    except ImportError as exc:
        raise ConfigError(
            "the anthropic package is not installed; run with `uv run --frozen --group translate`"
        ) from exc
    httpx = importlib.import_module("httpx")
    # The SDK resolves every credential source it knows at construction; fail
    # here, before any page work, rather than on the first request.
    try:
        client = sdk.Anthropic()
    except sdk.AnthropicError as exc:  # e.g. a credential profile it was pointed at is unreadable
        raise ConfigError(f"cannot set up the API client: {exc}") from exc
    if not (client.api_key or client.auth_token or client.credentials):
        raise ConfigError("no API credentials: set ANTHROPIC_API_KEY")

    class AnthropicTranslator:
        def complete(self, *, model: str, system: str, messages: Sequence[Message], max_tokens: int) -> Completion:
            prefix = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
            turns = [{"role": message.role, "content": message.content} for message in messages]
            try:
                with client.messages.stream(model=model, max_tokens=max_tokens, system=prefix, messages=turns) as s:
                    reply = s.get_final_message()
            except (sdk.AuthenticationError, sdk.PermissionDeniedError) as exc:
                raise ConfigError(f"the API rejected the credentials: {exc.message}") from exc
            except sdk.APIError as exc:
                raise PageError(f"API request failed: {exc.message}") from exc
            except httpx.HTTPError as exc:  # the SDK lets transport errors through raw once the stream is open
                raise PageError(f"API connection failed mid-reply: {exc!r}") from exc
            usage = Usage(
                reply.usage.input_tokens,
                reply.usage.output_tokens,
                reply.usage.cache_creation_input_tokens or 0,
                reply.usage.cache_read_input_tokens or 0,
            )
            text = "".join(block.text for block in reply.content if block.type == "text")
            return Completion(text, usage, reply.stop_reason)

    return AnthropicTranslator()


def glossary_prompt(glossary: Glossary) -> str:
    lines = ["## Glossary", "", "These terms always stay in English, spelled exactly like this:", ""]
    lines += [f"- {term}" for term in glossary.keep]
    if glossary.terms:
        lines += ["", "Use these renderings; the notes are binding:", ""]
    for term in glossary.terms:
        entry = f"- {term.source} → {term.target}"
        if term.avoid:
            entry += f" (never: {', '.join(term.avoid)})"
        if term.note:
            entry += f". {term.note}"
        lines.append(entry)
    return "\n".join(lines)


def system_prompt(inputs: Inputs) -> str:
    """The cacheable prefix shared by every page of a language: rules, instructions, glossary."""
    header = f"# Target language: {inputs.language.name} (`{inputs.language.code}`)"
    parts = (inputs.general_prompt, header, inputs.instructions, glossary_prompt(inputs.glossary))
    return "\n\n".join(part.strip() for part in parts)


def translate_request(english: str) -> str:
    return (
        "Translate the following Markdown page. Return only the translated page.\n\n"
        f"<english-page>\n{english}\n</english-page>"
    )


def update_request(english: str, changed: Sequence[str], previous: str) -> str:
    listed = "\n".join(f"- {label}" for label in changed)
    return (
        "This page was translated before. Retranslate it: translate the sections listed below\n"
        "afresh from the current English, applying the current language instructions and glossary\n"
        "(their previous wording may be outdated); everywhere else, reproduce the previous\n"
        "translation line by line, changing nothing. Keep the retranslated sections consistent in\n"
        "terminology and tone with their surroundings. A section is the introduction before the\n"
        "first `##` heading, or one `##` heading with everything under it.\n\n"
        f"Sections to retranslate:\n\n{listed}\n\n"
        f"Current English page:\n\n<english-page>\n{english}\n</english-page>\n\n"
        f"Previous translation of the page:\n\n<previous-translation>\n{previous}\n</previous-translation>\n\n"
        "Return only the full translated page."
    )


def repair_request(findings: Sequence[str]) -> str:
    listed = "\n".join(f"- {finding}" for finding in findings)
    return (
        "Your translation broke the following structural rules. Fix each problem and return the\n"
        f"full corrected page, changing nothing else:\n\n{listed}"
    )


# ---- Re-imposing the English structure on a reply, and validating what cannot be re-imposed ----


@dataclass(frozen=True)
class Mismatch:
    """A reply whose structure differs from the English; `partial` has the fences and ids that could be re-imposed."""

    findings: list[str]
    partial: str
    fences_restored: bool


def unwrap(english: str, reply: str) -> str:
    """Drop a code fence wrapping the whole reply, and match the English trailing newline."""
    match = None if english.startswith(("```", "~~~")) else _WRAPPER.match(reply)
    if match and match["close"][0] == match["open"][0] and len(match["close"]) >= len(match["open"]):
        reply = match["body"]
    if english.endswith("\n") and not reply.endswith("\n"):
        reply += "\n"
    return reply


def reimpose(english: str, ids: Sequence[str], reply: str) -> str | Mismatch:
    """Copy over the reply what the model must never change, and check the links it placed.

    `ids` are the renderer's ids for the English headings (`Repo.heading_ids`).
    Fences are copied opener-through-closer and `{#id}` blocks are pinned onto
    the translated headings positionally; each needs matching counts. Link and
    image targets are never moved (a translation may reorder links): each
    section must carry the same targets as its English, however placed.
    Otherwise the finding says what to fix.
    """
    findings: list[str] = []
    text, fences_restored = _restore_fences(english, reply, findings)
    text = _pin_headings(english, ids, text, findings)
    _check_targets(english, text, findings)
    return Mismatch(findings, text, fences_restored) if findings else text


def _restore_fences(english: str, reply: str, findings: list[str]) -> tuple[str, bool]:
    source, output = english.split("\n"), reply.split("\n")
    want, got = fence_ranges(source), fence_ranges(output)
    if unclosed := [fence for fence in got if not fence.closed]:
        findings.append(f"the code fence opened on line {unclosed[0].opener + 1} is never closed")
        return reply, False
    if len(want) != len(got):
        findings.append(f"{len(got)} code fences vs {len(want)} in the English: keep each code block, add none")
        return reply, False
    result: list[str] = []
    cursor = 0
    for expected, found in zip(want, got):
        result += output[cursor : found.opener]
        result += source[expected.opener : expected.closer + 1]
        cursor = found.closer + 1
    return "\n".join([*result, *output[cursor:]]), True


def _pin_headings(english: str, ids: Sequence[str], text: str, findings: list[str]) -> str:
    want, got = parse_headings(english), parse_headings(text)
    if len(want) != len(got):
        findings.append(f"{len(got)} headings vs {len(want)} in the English: keep every heading, and no others")
        return text
    if wrong := [(w, g) for w, g in zip(want, got) if w.level != g.level]:
        findings.extend(f"`{g.text}` is a level-{g.level} heading but `{w.text}` is level {w.level}" for w, g in wrong)
        return text
    lines = text.split("\n")
    for heading, anchor in zip(got, ids, strict=True):  # `Repo.heading_ids` pairs ids with these headings
        lines[heading.line] = f"{'#' * heading.level} {heading.text} {{#{anchor_source_form(anchor)}}}"
    return "\n".join(lines)


def _check_targets(english: str, text: str, findings: list[str]) -> None:
    """Compare link/image targets section by section, so any assembly of passing sections passes too."""
    want, got = sections(english), sections(text)
    if len(want) != len(got):  # the heading finding says so already; compare the pages whole
        want, got = [english], [text]
    missing: Counter[str] = Counter()
    extra: Counter[str] = Counter()
    for source, output in zip(want, got, strict=True):
        expected, found = Counter(link.target for link in links(source)), Counter(link.target for link in links(output))
        missing += expected - found
        extra += found - expected
    if missing:
        findings.append(f"missing links to {sorted(missing.elements())}: keep every link of the English where it is")
    if extra:
        findings.append(f"unexpected links to {sorted(extra.elements())}: add no links of your own")


def validate(english: str, output: str, glossary: Glossary) -> list[str]:
    """Findings for what re-imposition cannot fix (an empty list means the page passes)."""
    findings: list[str] = []
    want, got = code_spans(english), code_spans(output)
    if missing := sorted((want - got).elements()):
        findings.append(f"missing inline code {missing}: copy every `code span` of the English")
    if extra := sorted((got - want).elements()):
        findings.append(f"unexpected inline code {extra}: use only the English `code spans`")
    if markers(english) != markers(output):
        findings.append(
            f"block markers {markers(output)} vs {markers(english)} in the English:"
            " keep each `!!!`/`???`/`===` line and its type"
        )
    if table_rows(english) != table_rows(output):
        findings.append(f"table rows {table_rows(output)} vs {table_rows(english)} in the English")
    folded = mask(output).casefold()
    findings.extend(
        f"banned rendering {avoid!r} of {term.source!r} appears: use {term.target!r}"
        for term in glossary.terms
        for avoid in term.avoid
        if avoid.casefold() in folded
    )
    # Whatever the English itself carries is content, not an abridgement.
    placeholders = sorted((abridgements(output) - abridgements(english)).elements())
    findings.extend(f"placeholder {found!r}: translate the whole page, never abridge it" for found in placeholders)
    return findings


# ---- translate ----


@dataclass(frozen=True)
class Job:
    """One page selected for translation: which sections the model rewrites, and the prior text to keep."""

    state: PageState
    open: list[int]
    previous: Translation | None


def select_jobs(states: Sequence[PageState], *, pages: Sequence[str], grep: str | None) -> list[Job]:
    """The pages a run could work on, in nav order (the caller applies `--limit`).

    Raises:
        ConfigError: A `--pages` entry is not a translatable page, or `--grep` is not a valid regex.
    """
    if pages:
        by_key = {state.page.key: state for state in states}
        if unknown := [page for page in pages if page not in by_key]:
            raise ConfigError(f"not translatable pages (nav paths such as servers/tools.md): {unknown}")
        # A named page is translated from scratch, as a missing page is: every section is open,
        # so a previous translation would carry nothing forward and only anchor the model on it.
        return [Job(state, list(range(len(state.hashes))), None) for state in states if state.page.key in pages]
    selected: list[tuple[PageState, list[int]]] = []
    if grep is not None:
        try:
            pattern = re.compile(grep)
        except re.error as exc:
            raise ConfigError(f"--grep: invalid regular expression: {exc}") from exc
        for state in states:
            if state.status != "current":
                continue
            if matching := [index for index, text in enumerate(sections(state.english)) if pattern.search(text)]:
                selected.append((state, matching))
    else:
        for state in states:
            if state.status == "missing":
                selected.append((state, list(range(len(state.hashes)))))
            elif state.status == "outdated":
                selected.append((state, state.changed))
    return [_job(state, opened) for state, opened in selected]


def _job(state: PageState, opened: list[int]) -> Job:
    """Open only `opened` when the previous translation is usable for carry-forward, else the whole page."""
    previous = state.translation
    if previous is None or previous.provenance is None:
        return Job(state, list(range(len(state.hashes))), None)
    if len(previous.provenance.sections) != len(sections(previous.body)):
        return Job(state, list(range(len(state.hashes))), None)
    return Job(state, opened, previous)


def build_messages(job: Job) -> list[Message]:
    english = job.state.english
    if job.previous is None:
        return [Message("user", translate_request(english))]
    labels = [section_label(text, index) for index, text in enumerate(sections(english)) if index in job.open]
    return [Message("user", update_request(english, labels, job.previous.body))]


def carry_forward(job: Job, output: str) -> str:
    """Overwrite every section the model was not asked to rewrite with its previous translation.

    A section left closed is one whose English hash the previous file records
    (that is how `select_jobs` closes it), so the lookup cannot miss.
    """
    if job.previous is None or job.previous.provenance is None:
        return output
    prior = dict(zip(job.previous.provenance.sections, sections(job.previous.body), strict=True))
    kept = [
        text if index in job.open else prior[value]
        for index, (value, text) in enumerate(zip(job.state.hashes, sections(output), strict=True))
    ]
    return "".join(kept)


def _assemble(english: str, ids: Sequence[str], job: Job, output: str) -> str:
    """Carry unchanged sections forward, then re-impose once more so carried headings get today's ids."""
    result = reimpose(english, ids, carry_forward(job, output))
    if isinstance(result, Mismatch):
        raise PageError("; ".join(result.findings))
    return result


def _validate_open(english: str, body: str, job: Job, glossary: Glossary) -> list[str]:
    """`validate` over the sections this run rewrites; a carried section is published text, not this run's to fix."""
    pairs = zip(sections(english), sections(body), strict=True)
    rewritten = [pair for index, pair in enumerate(pairs) if index in job.open]
    return [finding for source, output in rewritten for finding in validate(source, output, glossary)]


def translate_page(repo: Repo, inputs: Inputs, job: Job, translator: Translator, model: str, usage: Usage) -> str:
    """Translate one page and return its body; token usage accumulates into `usage`.

    Raises:
        PageError: The page could not be produced (API failure, refusal, or unrepairable structure).
        ConfigError: The credentials were rejected.
    """
    english = job.state.english
    ids = repo.heading_ids(english)
    if not job.open:  # every English section still has a recorded translation: reassemble, no call
        return _assemble(english, ids, job, english)
    system, messages = system_prompt(inputs), build_messages(job)
    findings: list[str] = []
    for _ in range(1 + MAX_REPAIRS):
        completion = translator.complete(model=model, system=system, messages=messages, max_tokens=OUTPUT_TOKEN_BUDGET)
        usage.add(completion.usage)
        if completion.stop_reason == "max_tokens":
            raise PageError(f"the reply was cut off at {OUTPUT_TOKEN_BUDGET} output tokens")
        if completion.stop_reason == "refusal":
            raise PageError("the model declined to translate this page")
        result = reimpose(english, ids, unwrap(english, completion.text))
        if isinstance(result, Mismatch):
            findings = result.findings
        else:  # structure aligns, so the page can be assembled; what is checked is what would be written
            body = _assemble(english, ids, job, result)
            if not (findings := _validate_open(english, body, job, inputs.glossary)):
                return body
        messages += [Message("assistant", completion.text), Message("user", repair_request(findings))]
    raise PageError(f"unfixed after {MAX_REPAIRS} repairs: " + "; ".join(findings))


def command_translate(repo: Repo, args: argparse.Namespace, translator: Translator | None) -> int:
    language = repo.language(args.lang)
    inputs = repo.inputs(language)
    states = [classify(page) for page in repo.pages(language)]
    selected = select_jobs(states, pages=args.pages, grep=args.grep)
    # `--pages` names exactly the pages to run; any other selection is capped.
    jobs = selected if args.pages else selected[: args.limit]
    if not jobs:
        print(f"{language.code}: nothing to translate")
        return 0
    if len(jobs) < len(selected):
        print(f"{language.code}: {len(jobs)} of {len(selected)} selected pages this run (--limit); run again for more")
    if args.dry_run:
        system = system_prompt(inputs)
        print(f"===== system prompt, shared by every page (~{len(system) // 4} tokens) =====\n{system}")
        for job in jobs:
            content = "\n\n".join(message.content for message in build_messages(job))
            print(f"===== {job.state.page.key}: user message (~{len(content) // 4} tokens) =====\n{content}")
        print(f"{language.code}: {len(jobs)} page(s) selected; dry run, nothing sent (token counts are chars/4)")
        return 0
    # Deliberately never recorded in the generated files.
    model = os.environ.get("DOCS_TRANSLATE_MODEL") or repo.registry.model
    translator = translator or anthropic_translator()
    usage, failed = Usage(), False
    for job in jobs:
        page = job.state.page
        try:
            body = translate_page(repo, inputs, job, translator, model, usage)
        except PageError as exc:
            failed = True
            print(f"error: {page.key}: {exc}", file=sys.stderr)
            continue
        provenance = Provenance(tuple(job.state.hashes), inputs.hash)
        page.target.parent.mkdir(parents=True, exist_ok=True)
        page.target.write_text(with_provenance(body, provenance), encoding="utf-8", newline="\n")
        print(f"translated: {page.key} ({len(job.open)} of {len(job.state.hashes)} sections)", flush=True)
    print(f"usage: {usage}")
    return 1 if failed else 0


# ---- stage ----


@dataclass(frozen=True)
class Served:
    """What a language site shows for one page, and why when that is the English page."""

    body: str
    kind: NoticeKind
    reason: str = ""


def plan(repo: Repo, state: PageState) -> Served:
    """Decide what to serve for a translatable page; `status` predicts fallbacks through this too."""
    if state.status == "missing" or state.translation is None:
        return Served(state.english, "english")
    try:
        ids = repo.heading_ids(state.english)
    except PageError as exc:
        return Served(state.english, "english", str(exc))
    result = reimpose(state.english, ids, state.translation.body)
    if isinstance(result, Mismatch):
        # Structure drifted from today's English: serve it with what could be
        # re-imposed (`resolve_links` deals with targets that went dead), unless
        # the code blocks could not be restored — then only English is safe.
        if not result.fences_restored:
            return Served(state.english, "english", "; ".join(result.findings))
        body, reason = result.partial, "; ".join(result.findings)
    else:
        body, reason = result, ""
    if missing := [m["path"] for m in _SNIPPET.finditer(body) if not (repo.root / m["path"]).is_file()]:
        return Served(state.english, "english", f"snippet files not found: {missing}")
    return Served(body, "translated" if state.status == "current" else "outdated", reason)


def resolve_links(body: str, page: str, present: set[str], ids: dict[str, set[str]]) -> str:
    """Rewrite the page's prose links so every one resolves in the staged tree.

    Links into `api/` become site-absolute paths (language sites carry no API
    reference); a relative target the tree lacks loses its link but keeps its
    text; a `#fragment` the target page does not render is dropped.
    """
    edits: list[tuple[int, int, str]] = []
    directory = posixpath.dirname(page)
    for link in links(body):
        path, _, fragment = link.target.partition("#")
        if not link.target or not is_relative(link.target):
            continue
        resolved = posixpath.normpath(posixpath.join(directory, path)) if path else page
        if resolved.startswith(".."):
            continue
        if resolved == API_DIR or resolved.startswith(f"{API_DIR}/"):
            url = page_url(resolved) if resolved.endswith(".md") else resolved + ("/" if path.endswith("/") else "")
            edits.append((link.target_start, link.target_end, f"/{url}" + (f"#{fragment}" if fragment else "")))
        elif resolved != page and resolved not in present:
            edits.append((link.start, link.end, link.label))
        elif fragment and resolved.endswith(".md") and fragment not in ids.get(resolved, set()):
            edits.append((link.start, link.end, link.label) if not path else (link.target_start, link.target_end, path))
    return _replace_spans(body, edits)


def render_notice(notice: Notice, kind: NoticeKind, page: str, code: str) -> str:
    """The notice as an admonition (collapsed for translated pages) with its placeholder links filled."""
    body = notice.body.replace("(ENGLISH_PAGE)", f"(/{page_url(page)})")
    body = body.replace("(TRANSLATIONS_PAGE)", f"(/{code}/translations/)")
    marker = "???" if kind == "translated" else "!!!"
    title = notice.title.replace('"', "'")
    lines = [f'{marker} note "{title}"', "", *(f"    {line}" if line.strip() else "" for line in body.split("\n"))]
    return "\n".join(lines)


def page_title(body: str) -> Heading | None:
    """The page's first `#` heading, if it has one."""
    return next((heading for heading in parse_headings(body) if heading.level == 1), None)


def inject_notice(body: str, notice: str) -> str:
    """Place the notice right after the page's first `#` heading, or first if there is none."""
    lines = body.split("\n")
    title = page_title(body)
    if title is None:
        return f"{notice}\n\n{body}"
    rest = "\n".join(lines[title.line + 1 :]).lstrip("\n")
    return "\n".join([*lines[: title.line + 1], "", notice, "", rest])


def _is_staged(relative: Path) -> bool:
    """Whether a docs entry belongs in a language tree: not the generated `api/` tree, not a dot entry."""
    return relative.parts[:1] != (API_DIR,) and not any(part.startswith(".") for part in relative.parts)


def staged_paths(docs: Path) -> set[str]:
    """The docs-relative posix paths (files and directories) a staged tree carries."""
    return {"."} | {p.relative_to(docs).as_posix() for p in docs.rglob("*") if _is_staged(p.relative_to(docs))}


def stage(repo: Repo, language: Language) -> tuple[Path, list[tuple[str, Served]]]:
    """Build `.build/i18n/<code>/docs`: the English tree minus `api/`, translations overlaid, notices injected.

    Beside it, `titles.json` records each staged page's `#` heading for
    `build_config.py --lang` to title nav sections with. Only English and the
    generated pages are read (never the prompt inputs), so nothing a language
    maintainer edits by hand can break a site build.
    """
    states = {state.page.key: state for state in map(classify, repo.pages(language))}
    notices = dict(repo.notices)
    if (translated := plan(repo, states[NOTICES_PAGE])).kind == "translated":
        notices.update({key: value for key, value in parse_notices(translated.body).items() if key in notices})
    # Pages excluded from translation are staged as their English page.
    served = [
        (page, plan(repo, states[page]) if page in states else Served(read_english(repo.docs / page), "english"))
        for page in repo.prose_pages
    ]
    target = staged_docs_dir(language.code, repo.root)
    shutil.rmtree(target, ignore_errors=True)

    def left_out(directory: str, names: list[str]) -> set[str]:
        return {name for name in names if not _is_staged(Path(directory).relative_to(repo.docs) / name)}

    shutil.copytree(repo.docs, target, ignore=left_out)
    present = staged_paths(repo.docs)
    ids = {page: set(repo.render_ids(item.body)) for page, item in served}
    for page, item in served:
        body = resolve_links(item.body, page, present, ids)
        body = inject_notice(body, render_notice(notices[item.kind], item.kind, page, language.code))
        (target / page).write_text(body, encoding="utf-8", newline="\n")
    titles = {page: title.text for page, item in served if (title := page_title(item.body))}
    listing = json.dumps(titles, ensure_ascii=False, indent=0, sort_keys=True)
    staged_titles_file(language.code, repo.root).write_text(listing + "\n", encoding="utf-8", newline="\n")
    return target, served


def command_stage(repo: Repo, args: argparse.Namespace) -> int:
    language = repo.language(args.lang)
    target, served = stage(repo, language)
    for page, item in served:
        if item.kind == "english" and item.reason:
            print(f"{page}: served in English ({item.reason})", file=sys.stderr)
    print(f"staged {language.code} at {target.relative_to(repo.root).as_posix()}")
    return 0


# ---- status ----


def command_status(repo: Repo, args: argparse.Namespace) -> int:
    languages = [repo.language(args.lang)] if args.lang else list(repo.registry.languages)
    for language in languages:
        inputs = repo.inputs(language)
        states = [classify(page) for page in repo.pages(language)]
        strays = removable(repo, language)
        fallbacks = {state.page.key: served for state in states if (served := plan(repo, state)).reason}
        counts = Counter(state.status for state in states)
        english = sum(1 for served in fallbacks.values() if served.kind == "english")
        print(
            f"{language.code} ({language.name}): {counts['missing']} missing, {counts['outdated']} outdated,"
            f" {counts['current']} current, {len(strays)} removable, {english} english-fallback"
        )
        for state in states:
            if state.status != "current" or state.note:
                print(f"  {state.status:<9} {state.page.key}" + (f"  ({state.note})" if state.note else ""))
            if served := fallbacks.get(state.page.key):
                label, shown = ("fallback", "served in English") if served.kind == "english" else ("drifted", "served")
                print(f"  {label:<9} {state.page.key}  ({shown}; {served.reason})")
        for page in strays:
            print(f"  {'removable':<9} {page}  (git rm i18n/{language.code}/pages/{page})")
        if predating := sum(1 for state in states if state.predates(inputs)):
            print(f"  {predating} pages predate the current instructions/glossary (see `translate --grep`)")
    return 0


# ---- Command line ----


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="translations.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="what each language is missing, and what stage will serve")
    status.add_argument("--lang", metavar="CODE")
    translate = commands.add_parser(
        "translate",
        help="translate missing and outdated pages (calls the model)",
        description="Calls the model named in i18n/languages.yml, or in DOCS_TRANSLATE_MODEL if that is set.",
    )
    translate.add_argument("--lang", metavar="CODE", required=True)
    scope = translate.add_mutually_exclusive_group()
    scope.add_argument("--pages", nargs="+", metavar="PATH", default=[], help="re-translate these pages from scratch")
    scope.add_argument("--grep", metavar="REGEX", help="revise current pages, only sections whose English matches")
    translate.add_argument(
        "--limit", type=_positive, default=DEFAULT_LIMIT, metavar="N", help="at most N pages; does not cap --pages"
    )
    translate.add_argument("--dry-run", action="store_true", help="print the prompts; call nothing")
    staged = commands.add_parser("stage", help="assemble .build/i18n/CODE/docs for the site build")
    staged.add_argument("--lang", metavar="CODE", required=True)
    return parser


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT, translator: Translator | None = None) -> int:
    """Run one command against the checkout at `root`; returns the exit code."""
    args = _parser().parse_args(argv)
    try:
        repo = load_repo(root)
        if args.command == "status":
            return command_status(repo, args)
        if args.command == "translate":
            return command_translate(repo, args, translator)
        return command_stage(repo, args)
    except ConfigError as exc:
        print(f"translations: {exc}", file=sys.stderr)
        return 2
    # The process's top-level handler: a crash must not read as exit 1 ("some
    # pages failed"), whose partial output the workflow still proposes.
    except Exception as exc:
        traceback.print_exc()
        print(f"translations: internal error: {exc!r}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
