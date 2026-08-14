"""Machine-translate the documentation and stage each language site for the build.

Internal docs tooling, not part of the SDK. Maintained entirely by LLM; expect
breaking changes to its CLI, formats and internals at any time. Nothing here is
a supported interface.

English under `docs/` is the source of truth. Every language in
`i18n/languages.yml` gets generated pages under `i18n/<code>/pages/`, driven by
that language's hand-written `instructions.md` and `glossary.json` plus the
shared `i18n/general-prompt.md`. Corrections go into those inputs, never into
the generated pages. Each generated page records, in its own front matter, the
English section hashes it reflects; nothing else tracks state.

Usage (from the repository root):
    python scripts/docs/translations.py status [--lang CODE]
    python scripts/docs/translations.py translate --lang CODE [--pages PATH ...]
    python scripts/docs/translations.py stage [--lang CODE]

Only `translate` calls the model (credentials come from the environment, e.g.
`ANTHROPIC_API_KEY`) and needs the `translate` dependency group;
`DOCS_TRANSLATE_MODEL`, if set, replaces the registry's `model` for that run.
Exit codes: 0 done, 1 some page failed, 2 configuration or credential error.
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
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, cast, get_args

import markdown
import yaml
import zensical.config
from build_config import ROOT, Language, Registry, load_registry, nav_page_paths, staged_docs_dir, staged_titles_file
from llms_txt import CODE_SPAN, FRONT_MATTER, page_url
from zensical.config import ConfigurationError

# Zensical annotates its config loader `-> dict`; this is the shape its own renderer relies on.
parse_mkdocs_config = cast("Callable[[str], dict[str, Any]]", getattr(zensical.config, "parse_mkdocs_config"))

# Bumped only when the generated-file contract changes; older files then read as missing.
TOOL_VERSION = 1
# `max_tokens` per request: several times the longest page, leaving room for
# any thinking the model does, while inside the ceiling streaming allows.
OUTPUT_TOKEN_BUDGET = 64_000
# Repair turns fed back to the model after the first reply before a page fails.
MAX_REPAIRS = 2
NOTICES_PAGE = "i18n/notices.md"
# The nav page the notices link to for how the translations are made.
TRANSLATIONS_DOC = "translations.md"
API_DIR = "api"

Status = Literal["missing", "outdated", "current"]
NoticeKind = Literal["translated", "outdated", "english"]


class ConfigError(Exception):
    """Unusable configuration, inputs or credentials (exit code 2)."""


class PageError(Exception):
    """One page cannot be translated; the run continues with the next page."""


# ---- Markdown structure: fences, headings, code spans, links ----

# An ATX heading the way the renderer reads it: hashes at column 0, no space
# required after them, an optional closing hash run, backslash escapes honoured.
HEADING = re.compile(r"^(?P<hashes>#{1,6})(?!#)(?P<text>(?:\\.|[^\\\n])*?)#*[ \t]*$")
# A heading's trailing attr_list block(s), matched with or without the whitespace
# attr_list itself needs, so blocks the model glued to CJK text or doubled are
# still seen; `body` is the last block's, the one attr_list reads. Each block
# parses one way only (`{` to the next `}`), so no run of them can backtrack.
HEADING_ATTRS = re.compile(r"(?:[ \t]*\{(?P<body>[^}\n]*)\})+[ \t]*$")
ESCAPE = re.compile(r"\\(?P<char>[!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])")
# An underscore that is not word-internal turns into emphasis before attr_list
# reads the block, so it must be written escaped inside `{#...}`.
_BOUNDARY_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])")
_FENCE = re.compile(r"^[ \t]*(?P<run>`{3,}|~{3,})(?P<info>[^\n]*)$")
LINK = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)\s]*)[^)]*\)")
_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://(?:(?![<>)\]])[!-~])+")
_TAG = re.compile(r"</?[A-Za-z][^>\n]*>|<!--.*?-->", re.DOTALL)
_MARKER = re.compile(r"^[ \t]*(?P<marker>!!!|\?\?\?\+?|===)[ \t]+(?P<kind>[\w-]+)?")
# A bullet or ordered item at any depth, and a table row: block structure whose
# count a faithful translation keeps, whatever the language.
_LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
_TABLE_ROW = re.compile(r"^[ \t]*\|")
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
# A language site builds no API reference; links into `api/` go to the English one.
_API_LINK = re.compile(r"\]\((?:\.\./)*(?P<page>api/[^)#\s]+\.md)")


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


def split_front_matter(text: str) -> tuple[str | None, str]:
    """`(front matter YAML, body)`; the YAML is None when the page has no front matter block."""
    match = FRONT_MATTER.match(text)
    return (match["block"], text[match.end() :]) if match else (None, text)


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


def parse_headings(text: str) -> list[Heading]:
    """The ATX headings of `text` in order, with the id any trailing `{#...}` block pins."""
    found: list[Heading] = []
    for index, line in enumerate(_mask_fences(text).split("\n")):
        if not (match := HEADING.match(line)):
            continue
        heading, anchor = match["text"].strip(), None
        if attrs := HEADING_ATTRS.search(heading):
            tokens = attrs["body"].removeprefix(":").split()  # `{: ...}` is attr_list's other spelling
            ids = [token[1:] for token in tokens if token.startswith("#") and len(token) > 1]
            anchor = ESCAPE.sub(r"\g<char>", ids[-1]) if ids else None
            heading = heading[: attrs.start()].rstrip()
        found.append(Heading(index, len(match["hashes"]), heading, anchor))
    return found


def anchor_source_form(anchor: str) -> str:
    """The rendered id as it must be written inside `{#...}` to survive the emphasis pass."""
    return _BOUNDARY_UNDERSCORE.sub(r"\\_", anchor)


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


def link_targets(text: str) -> Counter[str]:
    """The targets of the markdown links and images written in the prose of `text`, counted."""
    return Counter(match["target"] for match in LINK.finditer(mask_code(text)))


def markers(text: str) -> list[str]:
    """The admonition (`!!!`/`???`) markers with their type keyword, and the tab (`===`) markers, in order."""
    matches = [match for line in _mask_fences(text).split("\n") if (match := _MARKER.match(line))]
    return ["===" if match["marker"] == "===" else f"{match['marker']} {match['kind'] or '?'}" for match in matches]


def block_counts(text: str) -> dict[str, int]:
    """How many list items and table rows the prose of `text` has (fenced code excluded)."""
    lines = mask_code(text).split("\n")
    patterns = {"list items": _LIST_ITEM, "table rows": _TABLE_ROW}
    return {kind: sum(1 for line in lines if pattern.match(line)) for kind, pattern in patterns.items()}


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


def section_hashes(body: str) -> list[str]:
    """The first 16 hex digits of each section's sha256."""
    return [hashlib.sha256(section.encode("utf-8")).hexdigest()[:16] for section in sections(body)]


def with_provenance(body: str, hashes: Sequence[str]) -> str:
    """The generated file: the English section hashes in front matter, then the translated body."""
    record = {"translation": {"sections": list(hashes), "tool": TOOL_VERSION}}
    header = yaml.safe_dump(record, sort_keys=False, default_flow_style=None, width=2**16)
    return f"---\n{header}---\n{body}"


def read_provenance(front_matter: str | None) -> tuple[str, ...] | None:
    """The section hashes a generated page records, or None if absent, unreadable or from another tool version."""
    try:
        record = yaml.safe_load(front_matter or "")["translation"]
        return tuple(str(value) for value in record["sections"]) if record["tool"] == TOOL_VERSION else None
    except (yaml.YAMLError, TypeError, KeyError):
        return None


# ---- The repository: registry, nav pages, prompt inputs and the renderer's heading ids ----


@dataclass(frozen=True)
class Term:
    source: str
    target: str
    note: str = ""
    avoid: Sequence[str] = ()


@dataclass(frozen=True)
class Glossary:
    keep: Sequence[str]
    terms: Sequence[Term]


def _strings(value: object) -> bool:
    """Whether `value` is a JSON list of strings (a bare string is not)."""
    return isinstance(value, list) and all(isinstance(item, str) for item in cast("list[object]", value))


def load_glossary(path: Path) -> Glossary:
    """Parse `glossary.json`: `keep` strings and `terms` objects with the `Term` fields.

    Raises:
        ConfigError: The file is missing, not JSON, or not that shape.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        keep, entries = raw["keep"], [dict(entry) for entry in raw["terms"]]
    except (OSError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
        raise ConfigError(f"{path}: {exc!r}") from exc
    if not _strings(keep):
        raise ConfigError(f"{path}: `keep` must be a list of strings")
    for entry in entries:
        texts = all(isinstance(entry.get(key, ""), str) for key in ("source", "target", "note"))
        if not (texts and _strings(entry.get("avoid", []))):
            raise ConfigError(f"{path}: `terms` entry {entry} needs string `source`/`target`/`note` and a list `avoid`")
    try:
        terms = tuple(Term(**entry) for entry in entries)  # a missing or unknown key is a TypeError
    except TypeError as exc:
        raise ConfigError(f"{path}: {exc!r}") from exc
    return Glossary(tuple(keep), terms)


@dataclass(frozen=True)
class Inputs:
    """One language's prompt inputs."""

    language: Language
    general_prompt: str
    instructions: str
    glossary: Glossary


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
    docs: Path
    i18n: Path
    registry: Registry
    prose_pages: list[str]
    translatable: list[str]
    renderer: markdown.Markdown

    def language(self, code: str) -> Language:
        for language in self.registry.languages:
            if language.code == code:
                return language
        known = ", ".join(language.code for language in self.registry.languages)
        raise ConfigError(f"unknown language {code!r} (i18n/languages.yml has: {known})")

    def inputs(self, language: Language) -> Inputs:
        try:
            general = (self.i18n / "general-prompt.md").read_text(encoding="utf-8")
            instructions = (self.i18n / language.code / "instructions.md").read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(str(exc)) from exc
        return Inputs(language, general, instructions, load_glossary(self.i18n / language.code / "glossary.json"))

    def pages(self, language: Language) -> list[Page]:
        """The language's translatable pages in nav order, then the notices page."""
        generated = self.i18n / language.code / "pages"
        pages = [Page(key, self.docs / key, generated / key) for key in self.translatable]
        return [*pages, Page(NOTICES_PAGE, self.root / NOTICES_PAGE, self.i18n / language.code / "notices.md")]

    def heading_ids(self, body: str) -> list[str]:
        """The ids the site renderer gives the page's headings, paired one-to-one with `parse_headings(body)`.

        Raises:
            PageError: The renderer sees headings the source scan does not (setext, indented, HTML).
        """
        self.renderer.reset()
        self.renderer.convert(body)
        tokens = cast("list[dict[str, Any]]", getattr(self.renderer, "toc_tokens", []))
        ids, found = [str(token["id"]) for token in _flatten(tokens)], parse_headings(body)
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
    # repository root; only heading ids are read here, so a missing one is not
    # this renderer's failure.
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
    """Read the registry and the nav of the checkout at `root`, and check its English notices.

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
    if missing := [kind for kind in get_args(NoticeKind) if kind not in notices]:
        raise ConfigError(f"{root / NOTICES_PAGE}: missing `## ... {{#id}}` sections for {missing}")
    translatable = [page for page in prose if not _excluded(page, registry.exclude)]
    return Repo(root, root / "docs", root / "i18n", registry, prose, translatable, _renderer(root))


# ---- Page status ----


@dataclass(frozen=True)
class Translation:
    """A generated page: the English section hashes it records (one per section of its body) and its body."""

    sections: tuple[str, ...]
    body: str


def recorded_sections(translation: Translation) -> dict[str, str]:
    """A generated page's sections keyed by the English section hash each records."""
    return dict(zip(translation.sections, sections(translation.body), strict=True))


@dataclass(frozen=True)
class PageState:
    """One page classified against the current English text; `translation` is None unless usable."""

    page: Page
    english: str
    hashes: list[str]
    translation: Translation | None
    status: Status
    changed: list[int] = field(default_factory=list[int])
    note: str = ""


def classify(page: Page) -> PageState:
    """Compare the page's recorded section hashes with the current English ones.

    Raises:
        ConfigError: The English source cannot be read.
    """
    english = read_english(page.source)
    hashes = section_hashes(english)
    if not page.target.is_file():
        return PageState(page, english, hashes, None, "missing")
    front_matter, body = split_front_matter(page.target.read_text(encoding="utf-8"))
    recorded = read_provenance(front_matter)
    if recorded is None or len(recorded) != len(sections(body)):
        return PageState(page, english, hashes, None, "missing", note="unreadable front matter, retranslated whole")
    translation = Translation(recorded, body)
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
    """Anything that answers a conversation (`ConfigError`: credentials rejected; `PageError`: request failed)."""

    def complete(self, *, model: str, system: str, messages: Sequence[Message], max_tokens: int) -> Completion: ...


def anthropic_translator() -> Translator:
    """The Claude Messages API client, streaming, with the system prompt as one cached block.

    `anthropic` lives in the non-default `translate` dependency group, so it is
    imported here, by name: offline commands and type checking never need it.

    Raises:
        ConfigError: The `translate` dependency group is not installed, or no credentials are configured.
    """
    try:
        sdk = importlib.import_module("anthropic")
    except ImportError as exc:
        raise ConfigError(
            "the anthropic package is not installed; run with `uv run --frozen --group translate`"
        ) from exc
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
    """A reply whose structure differs from the English; each finding says what to fix."""

    findings: list[str]


def unwrap(english: str, reply: str) -> str:
    """Drop a code fence wrapping the whole reply, and end it with exactly the English's trailing newlines."""
    match = None if english.startswith(("```", "~~~")) else _WRAPPER.match(reply)
    if match and match["close"][0] == match["open"][0] and len(match["close"]) >= len(match["open"]):
        reply = match["body"]
    return reply.rstrip("\n") + english[len(english.rstrip("\n")) :]


def reimpose(english: str, ids: Sequence[str], reply: str) -> str | Mismatch:
    """Copy over the reply what the model must never change, and check the links it placed.

    `ids` are the renderer's ids for the English headings (`Repo.heading_ids`).
    Fences are copied opener-through-closer within each section and `{#id}`
    blocks are pinned onto the translated headings positionally; each needs
    matching counts. Link and image targets are never moved (a translation may
    reorder links): each section must carry the same targets as its English,
    however placed. Checks go section by section, so any assembly of passing
    sections passes too.
    """
    findings: list[str] = []
    text = _restore_fences(english, reply, findings)
    text = _pin_headings(english, ids, text, findings)
    _check_targets(english, text, findings)
    return Mismatch(findings) if findings else text


def _paired_sections(english: str, text: str) -> list[tuple[str, str, str]]:
    """`(label, English section, its counterpart)` per section, or the pages whole if their counts differ."""
    want, got = sections(english), sections(text)
    if len(want) != len(got):  # the heading finding says so already
        return [("the page", english, text)]
    return [(section_label(source, index), source, output) for index, (source, output) in enumerate(zip(want, got))]


def _restore_fences(english: str, reply: str, findings: list[str]) -> str:
    if unclosed := [fence for fence in fence_ranges(reply.split("\n")) if not fence.closed]:
        findings.append(f"the code fence opened on line {unclosed[0].opener + 1} is never closed")
        return reply
    restored: list[str] = []
    for label, source, output in _paired_sections(english, reply):
        kept, lines = source.split("\n"), output.split("\n")
        want, got = fence_ranges(kept), fence_ranges(lines)
        if len(want) != len(got):
            findings.append(
                f"{label}: {len(got)} code fences vs {len(want)} in the English: keep each where it is, add none"
            )
            restored.append(output)
            continue
        result: list[str] = []
        cursor = 0
        for expected, found in zip(want, got):
            result += lines[cursor : found.opener]
            result += kept[expected.opener : expected.closer + 1]
            cursor = found.closer + 1
        restored.append("\n".join([*result, *lines[cursor:]]))
    return "".join(restored)


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
    missing: Counter[str] = Counter()
    extra: Counter[str] = Counter()
    for _, source, output in _paired_sections(english, text):
        expected, found = link_targets(source), link_targets(output)
        missing += expected - found
        extra += found - expected
    if missing:
        findings.append(f"missing links to {sorted(missing.elements())}: keep every link of the English where it is")
    if extra:
        findings.append(f"unexpected links to {sorted(extra.elements())}: add no links of your own")


def validate(english: str, output: str, glossary: Glossary, label: str = "the page") -> list[str]:
    """Findings for what re-imposition cannot fix (an empty list means `output`, called `label`, passes)."""
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
    counted = block_counts(output)
    findings.extend(
        f"{label}: {counted[kind]} {kind} vs {count} in the English: translate them one for one, dropping none"
        for kind, count in block_counts(english).items()
        if counted[kind] != count
    )
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


def select_jobs(states: Sequence[PageState], pages: Sequence[str]) -> list[Job]:
    """The missing and outdated pages with their changed sections open, or exactly `pages`, whole and fresh.

    Raises:
        ConfigError: A `pages` entry is not a translatable page.
    """
    if unknown := [page for page in pages if page not in {state.page.key for state in states}]:
        raise ConfigError(f"not translatable pages (nav paths such as servers/tools.md): {unknown}")
    if pages:  # a previous translation would carry nothing forward and only anchor the model on it
        return [_fresh(state) for state in states if state.page.key in pages]
    return [
        _fresh(state) if state.translation is None else Job(state, state.changed, state.translation)
        for state in states
        if state.status != "current"
    ]


def _fresh(state: PageState) -> Job:
    """The whole page from the English alone."""
    return Job(state, list(range(len(state.hashes))), None)


def build_messages(job: Job) -> list[Message]:
    english = job.state.english
    if job.previous is None:
        return [Message("user", translate_request(english))]
    labels = [section_label(text, index) for index, text in enumerate(sections(english)) if index in job.open]
    return [Message("user", update_request(english, labels, job.previous.body))]


def carry_forward(job: Job, output: str) -> str:
    """Overwrite every section the model was not asked to rewrite with its previous translation.

    A section left closed is one whose English hash the previous file records
    (that is how `classify` closes it), so the lookup cannot miss.
    """
    if job.previous is None:
        return output
    prior = recorded_sections(job.previous)
    paired = zip(job.state.hashes, sections(output), strict=True)
    return "".join(text if index in job.open else prior[value] for index, (value, text) in enumerate(paired))


def reassemble(repo: Repo, job: Job) -> str:
    """The page rebuilt from its recorded translations alone, for a job with no open section (no model call).

    Raises:
        PageError: The rebuilt page no longer fits the English structure.
    """
    english = job.state.english
    result = reimpose(english, repo.heading_ids(english), carry_forward(job, english))
    if isinstance(result, Mismatch):
        raise PageError("; ".join(result.findings))
    return result


def _validate_open(english: str, body: str, job: Job, glossary: Glossary) -> list[str]:
    """`validate` over the sections this run rewrites; a carried section is published text, not this run's to fix."""
    paired = enumerate(zip(sections(english), sections(body), strict=True))
    rewritten = [
        (section_label(source, index), source, output) for index, (source, output) in paired if index in job.open
    ]
    return [finding for label, source, output in rewritten for finding in validate(source, output, glossary, label)]


def translate_page(repo: Repo, inputs: Inputs, job: Job, translator: Translator, model: str, usage: Usage) -> str:
    """Translate one page and return its body; token usage accumulates into `usage`.

    Each reply has its carried sections overwritten before any check runs, so
    only text this run keeps can cost a repair turn or fail the page.

    Raises:
        PageError: The page could not be produced (API failure, refusal, or unrepairable structure).
        ConfigError: The credentials were rejected.
    """
    if not job.open:
        return reassemble(repo, job)
    english = job.state.english
    ids = repo.heading_ids(english)
    system, messages = system_prompt(inputs), build_messages(job)
    findings: list[str] = []
    for _ in range(1 + MAX_REPAIRS):
        completion = translator.complete(model=model, system=system, messages=messages, max_tokens=OUTPUT_TOKEN_BUDGET)
        usage.add(completion.usage)
        if completion.stop_reason == "max_tokens":
            raise PageError(f"the reply was cut off at {OUTPUT_TOKEN_BUDGET} output tokens")
        if completion.stop_reason == "refusal":
            raise PageError("the model declined to translate this page")
        reply = unwrap(english, completion.text)
        # Only a reply whose sections line up with the English can be assembled; one that
        # does not is checked as it stands and fails the heading check.
        if len(sections(reply)) == len(job.state.hashes):
            reply = carry_forward(job, reply)
        result = reimpose(english, ids, reply)  # today's ids pinned on carried sections too
        if isinstance(result, Mismatch):
            findings = result.findings
        elif not (findings := _validate_open(english, result, job, inputs.glossary)):  # checked as it would be written
            return result
        messages += [Message("assistant", completion.text), Message("user", repair_request(findings))]
    raise PageError(f"unfixed after {MAX_REPAIRS} repairs: " + "; ".join(findings))


def command_translate(repo: Repo, args: argparse.Namespace, translator: Translator | None) -> int:
    language = repo.language(args.lang)
    inputs = repo.inputs(language)
    jobs = select_jobs([classify(page) for page in repo.pages(language)], args.pages)
    if not jobs:
        print(f"{language.code}: nothing to translate")
        return 0
    model = os.environ.get("DOCS_TRANSLATE_MODEL") or repo.registry.model  # never recorded in the generated files
    # Only a job with open sections calls the model; a run without one needs no client and no
    # credentials. Otherwise both are set up here, so bad credentials fail before any page work.
    if translator is None and any(job.open for job in jobs):
        translator = anthropic_translator()
    usage, failed = Usage(), False
    for job in jobs:
        page = job.state.page
        try:
            body = translate_page(repo, inputs, job, translator, model, usage) if translator else reassemble(repo, job)
        except PageError as exc:
            failed = True
            print(f"error: {page.key}: {exc}", file=sys.stderr)
            continue
        page.target.parent.mkdir(parents=True, exist_ok=True)
        page.target.write_text(with_provenance(body, job.state.hashes), encoding="utf-8", newline="\n")
        print(f"translated: {page.key} ({len(job.open)} of {len(job.state.hashes)} sections)", flush=True)
    print(f"usage: {usage}")
    return 1 if failed else 0


# ---- stage ----


def serve(state: PageState) -> tuple[str, NoticeKind]:
    """What a language site shows for a page: its stored translation exactly as generated, else English.

    A generated page had its heading ids and code pinned against the English it
    was made from, so served verbatim it can never pair prose with another
    section's code or ids; bringing it up to date is the translate run's job.
    """
    if state.translation is None:
        return state.english, "english"
    return state.translation.body, "translated" if state.status == "current" else "outdated"


def english_site(page: str) -> str:
    """The English site root as a link from `page` on a language site reads it.

    The renderer resolves a page's relative links against its source path, so
    this climbs out of the page's directory, then out of the language site.
    """
    return "../" * page.count("/") + "../"


def render_notice(notice: Notice, kind: NoticeKind, page: str) -> str:
    """The notice as an admonition (collapsed for translated pages) with its placeholder links filled.

    Links are relative to the staged page, so they hold under whatever path the
    sites are served: the English page is the same path one site up, and the
    translations page is this site's own `translations.md`.
    """
    body = notice.body.replace("(ENGLISH_PAGE)", f"({english_site(page)}{page_url(page)})")
    body = body.replace("(TRANSLATIONS_PAGE)", f"({posixpath.relpath(TRANSLATIONS_DOC, posixpath.dirname(page))})")
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


def stage(repo: Repo, language: Language) -> Path:
    """Build `.build/i18n/<code>/docs`: the English tree minus `api/`, translations overlaid, notices injected.

    Beside it, `titles.json` records each staged page's `#` heading for
    `build_config.py --lang` to title nav sections with. Only English and the
    generated pages are read (never the prompt inputs), so nothing a language
    maintainer edits by hand can break a site build.
    """
    states = {state.page.key: state for state in map(classify, repo.pages(language))}
    notices_page = states.pop(NOTICES_PAGE)  # a kind its translation lacks (added since) stays English
    notices = {**parse_notices(notices_page.english), **parse_notices(serve(notices_page)[0])}
    target, titles_file = staged_docs_dir(language.code, repo.root), staged_titles_file(language.code, repo.root)
    # The titles file goes last, so it only ever sits beside a complete tree.
    titles_file.unlink(missing_ok=True)
    shutil.rmtree(target, ignore_errors=True)

    def left_out(directory: str, names: list[str]) -> list[str]:
        return [n for n in names if n.startswith(".") or (n == API_DIR and Path(directory) == repo.docs)]

    shutil.copytree(repo.docs, target, ignore=left_out)
    titles: dict[str, str] = {}
    for page in repo.prose_pages:  # a page excluded from translation is staged as its English page
        body, kind = serve(states[page]) if page in states else (read_english(repo.docs / page), "english")
        # The one API reference is the English site's.
        body = _API_LINK.sub(lambda match: f"]({english_site(page)}{page_url(match['page'])}", body)
        if title := page_title(body):
            titles[page] = title.text
        body = inject_notice(body, render_notice(notices[kind], kind, page))
        (target / page).write_text(body, encoding="utf-8", newline="\n")
    listing = json.dumps(titles, ensure_ascii=False, indent=0, sort_keys=True)
    titles_file.write_text(listing + "\n", encoding="utf-8", newline="\n")
    return target


def command_stage(repo: Repo, args: argparse.Namespace) -> int:
    for language in [repo.language(args.lang)] if args.lang else repo.registry.languages:
        target = stage(repo, language)
        print(f"staged {language.code} at {target.relative_to(repo.root).as_posix()}", flush=True)
    return 0


# ---- status ----


def command_status(repo: Repo, args: argparse.Namespace) -> int:
    languages = [repo.language(args.lang)] if args.lang else repo.registry.languages
    for language in languages:
        states = [classify(page) for page in repo.pages(language)]
        strays = removable(repo, language)
        counts = Counter(state.status for state in states)
        print(
            f"{language.code} ({language.name}): {counts['missing']} missing, {counts['outdated']} outdated,"
            f" {counts['current']} current, {len(strays)} removable"
        )
        for state in states:
            if state.status != "current":
                print(f"  {state.status:<9} {state.page.key}" + (f"  ({state.note})" if state.note else ""))
        for page in strays:
            print(f"  {'removable':<9} {page}  (git rm i18n/{language.code}/pages/{page})")
    return 0


# ---- Command line ----


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="translations.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="what each language is missing")
    status.add_argument("--lang", metavar="CODE")
    translate = commands.add_parser("translate", help="translate missing and outdated pages (calls the model)")
    translate.add_argument("--lang", metavar="CODE", required=True)
    translate.add_argument(
        "--pages", nargs="+", metavar="PATH", default=[], help="re-translate exactly these pages from scratch"
    )
    staged = commands.add_parser("stage", help="assemble .build/i18n/CODE/docs for the site build")
    staged.add_argument("--lang", metavar="CODE", help="stage this language only (default: every language)")
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


if __name__ == "__main__":
    raise SystemExit(main())
