"""`SkillCatalog`: a `Skills` extension backed by a `SkillProvider`."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import re
from bisect import bisect_left
from collections.abc import Callable, Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any, Literal, Self, TypeVar
from urllib.parse import quote

import anyio.to_thread
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

__all__ = ["SkillCatalog"]

logger = logging.getLogger(__name__)

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


class SkillCatalog(Skills):
    """A `Skills` extension that serves the skills found in a `SkillProvider`.

    Build one with `SkillCatalog.load()`, which scans the provider once; the
    catalog is then fixed for the server's lifetime. Every file of every valid
    skill becomes a `skill://` resource, so `skills/list` and `skills/get`
    manifests always match what `resources/read` returns.

    Pass it to `MCPServer(extensions=[catalog])`.
    """

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
        self._catalog_skills = tuple(skills)
        self._by_uri = {skill.uri: skill for skill in skills}
        self._files = dict(files)
        self._directories = directories
        self._cache = CacheableResult(ttl_ms=ttl_ms, cache_scope=cache_scope)
        self._page_size = page_size

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
                `load()` raises instead.
            directory_read: Also serve `resources/directory/read`, listing every directory
                that holds a served file.
            ttl_ms: `ttlMs` cache hint (SEP-2549) set on `skills/list`, `skills/get` and
                directory reads.
            cache_scope: `cacheScope` cache hint set on the same results.
            page_size: The maximum number of entries in one `skills/list` or directory read
                page. When `None`, every entry is returned in a single response. A skill entry
                is never split across pages.

        Raises:
            ValueError: If `strict` is set and any skill is invalid, if the provider
                lists a path that is empty, absolute, contains a `.` or `..` segment, appears
                twice, or lies beneath another listed file, or if `ttl_ms` is negative or
                `page_size` is less than 1.
            OSError: If the provider fails to list or read a file.
        """
        if page_size is not None and page_size < 1:
            raise ValueError("page_size must be at least 1")
        if ttl_ms < 0:
            raise ValueError("ttl_ms must not be negative")
        paths = _check_paths(list(await provider.list_files()))
        visible = sorted(path for path in paths if not any(segment.startswith(".") for segment in path.split("/")))
        skill_paths = [path for path in visible if path.split("/")[-1] == _SKILL_FILE]

        skills: dict[str, Skill] = {}
        served: set[str] = set()
        problems: list[str] = []
        skill_mds: dict[str, bytes] = {}
        fingerprints: dict[str, _Fingerprint] = {}
        for skill_path in skill_paths:
            if skill_path == _SKILL_FILE:
                problems.append(f"{skill_path}: a skill needs a directory name")
                continue
            skill_mds[skill_path] = await provider.read_file(skill_path)
            fingerprints[skill_path] = _fingerprint(skill_mds[skill_path])

        for skill_path, skill_md in skill_mds.items():
            try:
                skill, skill_files = await _load_skill(
                    provider, parse_frontmatter, skill_path, skill_md, visible, fingerprints
                )
            except ValueError as exc:
                problems.append(f"{skill_path}: {exc}")
                continue
            skills[skill_path] = skill
            served.update(skill_files)

        if problems:
            if strict:
                raise ValueError("invalid skills:\n" + "\n".join(problems))
            for problem in problems:
                logger.warning("Skipping invalid skill: %s", problem)

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
        return cls(
            skills=sorted(skills.values(), key=lambda skill: skill.uri),
            files=files,
            directories=_directory_index(files) if directory_read else None,
            ttl_ms=ttl_ms,
            cache_scope=cache_scope,
            page_size=page_size,
        )

    def resources(self) -> Sequence[ResourceBinding]:
        """One binding per served file, sorted by URI."""
        return [ResourceBinding(resource=file) for file in sorted(self._files.values(), key=lambda f: f.uri)]

    async def _list_handler(self, ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
        page, next_cursor = _paginate(self._catalog_skills, params.cursor, self._page_size)
        return ListSkillsResult(
            skills=page,
            next_cursor=next_cursor,
            ttl_ms=self._cache.ttl_ms,
            cache_scope=self._cache.cache_scope,
        )

    async def _get_handler(self, ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> GetSkillResult:
        skill = self._by_uri.get(params.uri)
        if skill is None:
            raise MCPError(code=INVALID_PARAMS, message=f"unknown skill: {params.uri}")
        return GetSkillResult(skill=skill, ttl_ms=self._cache.ttl_ms, cache_scope=self._cache.cache_scope)

    async def _read_directory_handler(
        self, ctx: ServerRequestContext[Any, Any], params: ReadDirectoryParams
    ) -> ReadDirectoryResult:
        assert self._directories is not None
        children = self._directories.get(params.uri)
        if children is None:
            raise MCPError(code=INVALID_PARAMS, message=f"unknown directory: {params.uri}")
        page, next_cursor = _paginate(children, params.cursor, self._page_size)
        return ReadDirectoryResult(
            resources=page,
            next_cursor=next_cursor,
            ttl_ms=self._cache.ttl_ms,
            cache_scope=self._cache.cache_scope,
        )


_T = TypeVar("_T")


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def _paginate(items: Sequence[_T], cursor: str | None, page_size: int | None) -> tuple[list[_T], str | None]:
    """Return one page of `items` and the cursor for the next page, if any.

    The catalog is immutable, so a cursor is just an offset into `items`, and no state is kept
    about which cursors were issued. Only an offset on a page boundary, in canonical form, is
    accepted; anything else is Invalid params.
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
