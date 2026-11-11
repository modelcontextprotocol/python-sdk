"""`SkillCatalog`: a `Skills` extension backed by a `SkillProvider`."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import mimetypes
import re
from bisect import bisect_left
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any, Literal, Self, TypeVar
from urllib.parse import quote

import anyio.to_thread
from anyio import sleep
from mcp_types import INVALID_PARAMS, CacheableResult
from mcp_types import Resource as ResourceEntry
from pydantic import BaseModel, PrivateAttr, TypeAdapter, ValidationError
from pydantic_core import to_jsonable_python

from mcp.server.context import ServerRequestContext
from mcp.server.extension import ResourceBinding
from mcp.server.mcpserver.exceptions import ResourceError
from mcp.server.mcpserver.resources import Resource
from mcp.server.skills._extension import Skills
from mcp.server.skills.provider import SkillProvider
from mcp.shared.exceptions import MCPError
from mcp.shared.skills import (
    MAX_RESOURCES_PER_SKILL,
    MAX_TOTAL_SIZE,
    Frontmatter,
    GetSkillParams,
    GetSkillResult,
    ListSkillsParams,
    ListSkillsResult,
    ReadDirectoryParams,
    ReadDirectoryResult,
    Skill,
    SkillResource,
)

__all__ = ["SkillCatalog", "SkillCatalogChanges"]

logger = logging.getLogger(__name__)

_DEFAULT_REFRESH_INTERVAL = 60.0
_SKILL_FILE = "SKILL.md"
_DIRECTORY_MIME_TYPE = "inode/directory"
_FRONTMATTER_DELIMITER = "---"
_MIME_TYPE_OVERRIDES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}


class _Fingerprint(BaseModel, frozen=True):
    digest: str
    size: int


_FRONTMATTER_ADAPTER: TypeAdapter[Frontmatter] = TypeAdapter(Frontmatter)


class _SkillFileResource(Resource):
    """One file of a skill, read from the provider on every `resources/read`.

    The bytes are checked against the digest taken at load time, so a manifest
    entry never describes content other than what is served.
    """

    _provider: SkillProvider = PrivateAttr()
    _path: str = PrivateAttr()
    _fingerprint: _Fingerprint = PrivateAttr()

    def __init__(self, *, provider: SkillProvider, path: str, fingerprint: _Fingerprint, **data: Any) -> None:
        super().__init__(**data)
        self._provider = provider
        self._path = path
        self._fingerprint = fingerprint

    @property
    def size(self) -> int:
        return self._fingerprint.size

    async def read(self) -> str | bytes:
        data = await self._provider.read_file(self._path)
        if _fingerprint(data) != self._fingerprint:
            raise ResourceError(f"{self.uri} changed since the catalog was loaded")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data


@dataclass(frozen=True)
class SkillCatalogChanges:
    """What `SkillCatalog.reload()` changed, as the `SKILL.md` URIs of the skills affected."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]
    """Skills still served whose listing entry differs: frontmatter, or the size or digest of any file."""


@dataclass(frozen=True)
class _Source:
    """What `reload()` needs to scan the provider again."""

    provider: SkillProvider
    parse_frontmatter: Callable[[str], Mapping[str, Any]]
    strict: bool
    retain_bytes: bool


class _SnapshotProvider:
    """Retain exactly the bytes used to construct one catalog generation."""

    def __init__(self, provider: SkillProvider) -> None:
        self._provider = provider
        self._content: dict[str, bytes] = {}

    async def list_files(self) -> Sequence[str]:
        return await self._provider.list_files()

    async def read_file(self, path: str) -> bytes:
        if path not in self._content:
            self._content[path] = await self._provider.read_file(path)
        return self._content[path]


@dataclass(frozen=True)
class _Scan:
    """What one pass over a provider found."""

    skills: dict[str, Skill]
    """The valid skills, by the path of their `SKILL.md`."""
    files: dict[str, _SkillFileResource]
    problems: dict[str, str]
    """Why each invalid skill was rejected, by the path of its `SKILL.md`."""


@dataclass(frozen=True)
class _CatalogState:
    """Everything a catalog serves, replaced as one unit by `reload()`."""

    skills: tuple[Skill, ...]
    by_uri: Mapping[str, Skill]
    bindings: tuple[ResourceBinding, ...]
    directories: Mapping[str, Sequence[ResourceEntry]] | None
    skill_paths: frozenset[str] = frozenset()
    problems: frozenset[str] = frozenset()


def _build_state(
    skills: Iterable[Skill],
    files: Mapping[str, Resource],
    directories: Mapping[str, Sequence[ResourceEntry]] | None,
    skill_paths: Iterable[str] = (),
    problems: Iterable[str] = (),
) -> _CatalogState:
    ordered = tuple(sorted(skills, key=lambda skill: skill.uri))
    return _CatalogState(
        skills=ordered,
        by_uri={skill.uri: skill for skill in ordered},
        bindings=tuple(ResourceBinding(resource=file) for file in sorted(files.values(), key=lambda f: str(f.uri))),
        directories=directories,
        skill_paths=frozenset(skill_paths),
        problems=frozenset(problems),
    )


class SkillCatalog(Skills):
    """A `Skills` extension that serves the skills found in a `SkillProvider`.

    Build one with `SkillCatalog.load()`, which scans the provider. Every file of every
    valid skill becomes a `skill://` resource, so `skills/list` and `skills/get`
    manifests always match what `resources/read` returns. `reload()` scans the provider
    again and replaces everything at once; with `auto_refresh` it does so on a timer.

    Pass it to `MCPServer(extensions=[catalog])`.
    """

    resources_are_dynamic = True

    def __init__(
        self,
        *,
        skills: Sequence[Skill],
        files: Mapping[str, Resource],
        directories: Mapping[str, Sequence[ResourceEntry]] | None,
        ttl_ms: int,
        cache_scope: Literal["public", "private"],
        page_size: int | None,
    ) -> None:
        """Assemble a catalog from already-validated parts. Use `SkillCatalog.load()`, which builds them.

        Raises:
            ValidationError: If `ttl_ms` is negative.
        """
        super().__init__(
            list_skills=self._list_handler,
            get_skill=self._get_handler,
            read_directory=self._read_directory_handler if directories is not None else None,
        )
        self._state = _build_state(skills, files, directories)
        self._cache = CacheableResult(ttl_ms=ttl_ms, cache_scope=cache_scope)
        self._page_size = page_size
        self._source: _Source | None = None
        self._reload_lock = anyio.Lock()
        self._refresh_lock = anyio.Lock()
        self._refresh_interval: float | None = None

    @classmethod
    async def load(
        cls,
        provider: SkillProvider,
        *,
        parse_frontmatter: Callable[[str], Mapping[str, Any]],
        strict: bool = False,
        directory_read: bool = False,
        ttl_ms: int = 0,
        cache_scope: Literal["public", "private"] = "private",
        page_size: int | None = None,
        auto_refresh: bool = False,
        refresh_interval: float = _DEFAULT_REFRESH_INTERVAL,
    ) -> Self:
        """Scan `provider` and build a catalog of the skills it holds.

        A skill is a directory containing a `SKILL.md`; the skill's files are everything
        beneath that directory, including files of skills nested inside it. Paths with a
        segment starting with `.` are ignored entirely.

        Args:
            provider: Where the skill files live.
            parse_frontmatter: Parses the text between the `---` lines of a `SKILL.md` (for
                example `yaml.safe_load`). It must return a mapping with `str` keys; the
                SDK deliberately has no YAML dependency of its own.
            strict: When `False`, a skill that is not valid (bad frontmatter, a name that
                doesn't match its directory, ...) is skipped with a warning. When `True`,
                `load()` raises instead. `reload()` also raises for any invalid skill when
                `True`; when `False` it raises only if a skill it is serving became invalid.
            directory_read: Also serve `resources/directory/read`, listing every directory
                that holds a served file.
            ttl_ms: `ttlMs` cache hint (SEP-2549) set on `skills/list`, `skills/get` and
                directory reads.
            cache_scope: `cacheScope` cache hint set on the same results.
            page_size: The maximum number of entries in one `skills/list` or directory read
                page. When `None`, every entry is returned in a single response. A skill entry
                is never split across pages.
            auto_refresh: Call `reload()` every `refresh_interval` seconds while the server
                runs. Off by default; without it the catalog changes only when you call
                `reload()`. The catalog then keeps the bytes it scanned in memory, so a file
                edited between refreshes is still served consistently with its manifest.
                A refresh that fails is logged and the previous catalog keeps serving.
            refresh_interval: Seconds between automatic reloads. Must be finite and greater
                than zero. Only used when `auto_refresh` is set.

        Raises:
            ValueError: If `strict` is set and any skill is invalid, if the provider
                lists a path that is empty, absolute, contains a `.` or `..` segment, appears
                twice, or lies beneath another listed file, or if `ttl_ms` is negative,
                `page_size` is less than 1, or `refresh_interval` is not finite and positive.
            OSError: If the provider fails to list or read a file.
        """
        if page_size is not None and page_size < 1:
            raise ValueError("page_size must be at least 1")
        if ttl_ms < 0:
            raise ValueError("ttl_ms must not be negative")
        if not math.isfinite(refresh_interval) or refresh_interval <= 0:
            raise ValueError("refresh_interval must be finite and greater than zero")
        scan = await _scan(_SnapshotProvider(provider) if auto_refresh else provider, parse_frontmatter)
        _reject_or_warn(scan.problems, strict)
        catalog = cls(
            skills=list(scan.skills.values()),
            files=scan.files,
            directories=_directory_index(scan.files) if directory_read else None,
            ttl_ms=ttl_ms,
            cache_scope=cache_scope,
            page_size=page_size,
        )
        catalog._state = replace(catalog._state, skill_paths=frozenset(scan.skills), problems=frozenset(scan.problems))
        catalog._source = _Source(provider, parse_frontmatter, strict, retain_bytes=auto_refresh)
        catalog._refresh_interval = refresh_interval if auto_refresh else None
        return catalog

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Run automatic refreshes, when enabled, until the server lifespan ends."""
        if self._refresh_interval is None:
            yield
            return
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(self._refresh_loop, self._refresh_interval)
            try:
                yield
            finally:
                tasks.cancel_scope.cancel()

    async def _refresh_loop(self, interval: float) -> None:
        # Per-connection lifespans share one worker; the next takes over when it exits.
        async with self._refresh_lock:
            while True:
                await sleep(interval)
                try:
                    await self.reload()
                except Exception:  # Top-level worker boundary: custom providers must not stop future refreshes.
                    logger.exception("Failed to refresh skills; continuing to serve the previous catalog")

    async def reload(self) -> SkillCatalogChanges:
        """Scan the provider again and replace everything the catalog serves, all at once.

        The whole provider is scanned and validated first, and only then swapped in, in a
        single step. Skills and files may be added, removed or edited. If anything fails,
        nothing changes and the previous catalog keeps serving. Concurrent calls run one
        after another.

        A scan fails if any skill is invalid and `strict` was set, or if a skill that is
        currently served became invalid, so a half-edited `SKILL.md` never takes a skill
        down. Skills that were already skipped at load stay skipped.

        Clients may keep `skills/list` results for `ttl_ms`, so they can see old entries
        until that expires, and nothing is pushed to connected clients.

        Returns:
            The skills added, removed or changed.

        Raises:
            ValueError: If the scan finds an invalid skill as described above, or the
                provider lists a path that is not valid.
            OSError: If the provider fails to list or read a file.
            RuntimeError: If this catalog was not built by `SkillCatalog.load()`.
        """
        source = self._source
        if source is None:
            raise RuntimeError("this catalog has no provider to rescan; build it with SkillCatalog.load()")
        async with self._reload_lock:
            current = self._state
            scan = await _scan(
                _SnapshotProvider(source.provider) if source.retain_bytes else source.provider,
                source.parse_frontmatter,
            )
            blocking = (
                scan.problems
                if source.strict
                else {path: reason for path, reason in scan.problems.items() if path in current.skill_paths}
            )
            _reject_or_warn(blocking, strict=True)
            for path in scan.problems.keys() - current.problems:
                logger.warning("Skipping invalid skill: %s: %s", path, scan.problems[path])
            state = _build_state(
                scan.skills.values(),
                scan.files,
                _directory_index(scan.files) if current.directories is not None else None,
                scan.skills,
                scan.problems,
            )
            # Nothing below awaits, so no request sees a half-applied reload.
            self._state = state
            return _diff(current.skills, state.skills)

    def resources(self) -> Sequence[ResourceBinding]:
        """One binding per served file, sorted by URI."""
        return self._state.bindings

    async def _list_handler(self, ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
        page, next_cursor = _paginate(self._state.skills, params.cursor, self._page_size)
        return ListSkillsResult(
            skills=page,
            next_cursor=next_cursor,
            ttl_ms=self._cache.ttl_ms,
            cache_scope=self._cache.cache_scope,
        )

    async def _get_handler(self, ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> GetSkillResult:
        skill = self._state.by_uri.get(params.uri)
        if skill is None:
            raise MCPError(code=INVALID_PARAMS, message=f"unknown skill: {params.uri}")
        return GetSkillResult(skill=skill, ttl_ms=self._cache.ttl_ms, cache_scope=self._cache.cache_scope)

    async def _read_directory_handler(
        self, ctx: ServerRequestContext[Any, Any], params: ReadDirectoryParams
    ) -> ReadDirectoryResult:
        assert self._state.directories is not None
        children = self._state.directories.get(params.uri)
        if children is None:
            raise MCPError(code=INVALID_PARAMS, message=f"unknown directory: {params.uri}")
        page, next_cursor = _paginate(children, params.cursor, self._page_size)
        return ReadDirectoryResult(
            resources=page,
            next_cursor=next_cursor,
            ttl_ms=self._cache.ttl_ms,
            cache_scope=self._cache.cache_scope,
        )


async def _scan(provider: SkillProvider, parse_frontmatter: Callable[[str], Mapping[str, Any]]) -> _Scan:
    """Read every skill in `provider`: the valid skills, the files they serve, and why any other was rejected.

    Raises:
        ValueError: If the provider lists an invalid path.
        OSError: If the provider fails to list or read a file.
    """
    paths = _check_paths(list(await provider.list_files()))
    visible = sorted(path for path in paths if not any(segment.startswith(".") for segment in path.split("/")))
    skill_paths = [path for path in visible if path.split("/")[-1] == _SKILL_FILE]

    skills: dict[str, Skill] = {}
    served: set[str] = set()
    problems: dict[str, str] = {}
    skill_mds: dict[str, bytes] = {}
    fingerprints: dict[str, _Fingerprint] = {}
    for skill_path in skill_paths:
        if skill_path == _SKILL_FILE:
            problems[skill_path] = "a skill needs a directory name"
            continue
        skill_mds[skill_path] = await provider.read_file(skill_path)
        fingerprints[skill_path] = _fingerprint(skill_mds[skill_path])

    for skill_path, skill_md in skill_mds.items():
        try:
            skill, skill_files = await _load_skill(
                provider, parse_frontmatter, skill_path, skill_md, visible, fingerprints
            )
        except ValueError as exc:
            problems[skill_path] = str(exc)
            continue
        skills[skill_path] = skill
        served.update(skill_files)

    # `mimetypes` reads system files the first time it is used, which must not block the event loop.
    mime_types = await anyio.to_thread.run_sync(_guess_mime_types, sorted(served))
    files = {
        path: _file_resource(
            provider,
            path,
            fingerprints[path],
            mime_types[path],
            skills[path].frontmatter if path in skills else None,
        )
        for path in sorted(served)
    }
    return _Scan(skills, files, problems)


def _reject_or_warn(problems: Mapping[str, str], strict: bool) -> None:
    if not problems:
        return
    if strict:
        raise ValueError("invalid skills:\n" + "\n".join(f"{path}: {reason}" for path, reason in problems.items()))
    for path, reason in problems.items():
        logger.warning("Skipping invalid skill: %s: %s", path, reason)


def _diff(old: Sequence[Skill], new: Sequence[Skill]) -> SkillCatalogChanges:
    before = {skill.uri: skill for skill in old}
    after = {skill.uri: skill for skill in new}
    return SkillCatalogChanges(
        added=tuple(sorted(after.keys() - before.keys())),
        removed=tuple(sorted(before.keys() - after.keys())),
        changed=tuple(sorted(uri for uri in before.keys() & after.keys() if before[uri] != after[uri])),
    )


_T = TypeVar("_T")


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def _paginate(items: Sequence[_T], cursor: str | None, page_size: int | None) -> tuple[list[_T], str | None]:
    """Return one page of `items` and the cursor for the next page, if any.

    A cursor is an offset into the current generation, not a snapshot across reloads.
    Only an offset on a page boundary, in canonical form, is accepted; anything else is
    Invalid params.
    """
    if page_size is None:
        if cursor is not None:
            raise MCPError(code=INVALID_PARAMS, message="this server does not paginate; unexpected cursor")
        return list(items), None
    start = 0
    if cursor is not None:
        try:
            start = int(base64.urlsafe_b64decode(cursor.encode("ascii")))
        except ValueError:
            start = -1
        if not (0 < start < len(items) and start % page_size == 0 and _encode_cursor(start) == cursor):
            raise MCPError(code=INVALID_PARAMS, message="invalid cursor")
    end = start + page_size
    return list(items[start:end]), _encode_cursor(end) if end < len(items) else None


def _check_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    for path in paths:
        if any(segment in ("", ".", "..") for segment in path.split("/")):
            raise ValueError(f"provider listed an invalid path {path!r}")
        if path in seen:
            raise ValueError(f"provider listed {path!r} more than once")
        seen.add(path)
    for path in paths:
        segments = path.split("/")
        for depth in range(1, len(segments)):
            if "/".join(segments[:depth]) in seen:
                raise ValueError(f"provider listed {path!r} beneath {'/'.join(segments[:depth])!r}, which is a file")
    return paths


def _paths_under(sorted_paths: Sequence[str], prefix: str) -> list[str]:
    """Return the paths that start with `prefix`; they are contiguous in sorted order, so no full scan is needed."""
    start = bisect_left(sorted_paths, prefix)
    end = start
    while end < len(sorted_paths) and sorted_paths[end].startswith(prefix):
        end += 1
    return list(sorted_paths[start:end])


def _fingerprint(data: bytes) -> _Fingerprint:
    return _Fingerprint(digest=hashlib.sha256(data).hexdigest(), size=len(data))


async def _load_skill(
    provider: SkillProvider,
    parse_frontmatter: Callable[[str], Mapping[str, Any]],
    skill_path: str,
    skill_md: bytes,
    sorted_visible: Sequence[str],
    fingerprints: dict[str, _Fingerprint],
) -> tuple[Skill, list[str]]:
    """Build the `Skill` whose `SKILL.md` is `skill_path`, along with the paths of its files.

    Raises:
        ValueError: If the skill is not valid.
    """
    frontmatter = _parse_frontmatter(skill_md, parse_frontmatter)
    root = skill_path.removesuffix(_SKILL_FILE)
    skill_files = _paths_under(sorted_visible, root)
    for path in skill_files:
        if path not in fingerprints:
            fingerprints[path] = _fingerprint(await provider.read_file(path))
    resources = sorted(
        (
            SkillResource(uri=_uri(path), digest=f"sha256:{fingerprints[path].digest}", size=fingerprints[path].size)
            for path in skill_files
        ),
        key=lambda resource: resource.uri,
    )
    try:
        skill = Skill(uri=_uri(skill_path), frontmatter=frontmatter, resources=resources)
    except ValidationError as exc:
        raise ValueError("; ".join(error["msg"].removeprefix("Value error, ") for error in exc.errors())) from None
    _warn_over_limits(skill.uri, resources)
    return skill, skill_files


def _parse_frontmatter(data: bytes, parse: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        text = data.decode("utf-8").removeprefix("\ufeff")
    except UnicodeDecodeError:
        raise ValueError("SKILL.md is not valid UTF-8") from None
    lines = re.split(r"\r?\n", text)
    if lines[0] != _FRONTMATTER_DELIMITER:
        raise ValueError("SKILL.md must start with a '---' frontmatter line")
    try:
        end = lines.index(_FRONTMATTER_DELIMITER, 1)
    except ValueError:
        raise ValueError("SKILL.md frontmatter has no closing '---' line") from None
    try:
        parsed = parse("\n".join(lines[1:end]))
    except Exception as exc:  # the parser is caller-supplied, so any failure marks the skill invalid
        raise ValueError(f"frontmatter could not be parsed: {exc}") from exc
    try:
        frontmatter = to_jsonable_python(_FRONTMATTER_ADAPTER.validate_python(parsed))
        json.dumps(
            frontmatter, allow_nan=False
        )  # NaN and infinity have no JSON form, so they can't pass through verbatim
        return frontmatter
    except (ValidationError, ValueError) as exc:
        raise ValueError("frontmatter must be a mapping with string keys and JSON-compatible values") from exc


def _warn_over_limits(skill_uri: str, resources: Sequence[SkillResource]) -> None:
    total = sum(resource.size for resource in resources)
    if len(resources) > MAX_RESOURCES_PER_SKILL:
        logger.warning(
            "Skill %s lists %d files, over the recommended %d", skill_uri, len(resources), MAX_RESOURCES_PER_SKILL
        )
    if total > MAX_TOTAL_SIZE:
        logger.warning("Skill %s totals %d bytes, over the recommended %d", skill_uri, total, MAX_TOTAL_SIZE)


def _uri(path: str) -> str:
    return "skill://" + "/".join(quote(segment, safe="") for segment in path.split("/"))


def _guess_mime_type(path: str) -> str:
    # `mimetypes` consults the host's tables, which differ by platform and don't always know Markdown.
    return (
        _MIME_TYPE_OVERRIDES.get(PurePosixPath(path).suffix.lower())
        or mimetypes.guess_type(path)[0]
        or "application/octet-stream"
    )


def _guess_mime_types(paths: Sequence[str]) -> dict[str, str]:
    return {path: _guess_mime_type(path) for path in paths}


def _file_resource(
    provider: SkillProvider,
    path: str,
    fingerprint: _Fingerprint,
    mime_type: str,
    skill_frontmatter: Mapping[str, Any] | None,
) -> _SkillFileResource:
    name = path.split("/")[-1]
    description = None
    if skill_frontmatter is not None:
        name = skill_frontmatter["name"]
        description = skill_frontmatter["description"]
    return _SkillFileResource(
        provider=provider,
        path=path,
        fingerprint=fingerprint,
        uri=_uri(path),
        name=name,
        description=description,
        mime_type=mime_type,
    )


def _directory_index(files: Mapping[str, _SkillFileResource]) -> dict[str, list[ResourceEntry]]:
    """Map each directory URI to its direct children, built from the served files only."""
    index: dict[str, dict[str, ResourceEntry]] = {}
    for path, file in files.items():
        segments = path.split("/")
        for depth in range(1, len(segments)):
            parent = _uri("/".join(segments[:depth]))
            child_path = "/".join(segments[: depth + 1])
            if depth + 1 == len(segments):
                entry = ResourceEntry(
                    uri=file.uri,
                    name=file.name or segments[-1],
                    description=file.description,
                    mime_type=file.mime_type,
                    size=file.size,
                )
            else:
                entry = ResourceEntry(uri=_uri(child_path), name=segments[depth], mime_type=_DIRECTORY_MIME_TYPE)
            index.setdefault(parent, {})[entry.uri] = entry
    return {uri: [children[child] for child in sorted(children)] for uri, children in index.items()}
