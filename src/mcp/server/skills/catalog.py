"""`SkillCatalog`: a `Skills` extension backed by a `SkillProvider`."""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import quote

import anyio.to_thread
from mcp_types import INVALID_PARAMS
from mcp_types import Resource as ResourceEntry
from pydantic import PrivateAttr, ValidationError
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


@dataclass(frozen=True)
class _Fingerprint:
    digest: str
    size: int


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
        files: Mapping[str, _SkillFileResource],
        directories: Mapping[str, Sequence[ResourceEntry]] | None,
        ttl_ms: int,
        cache_scope: Literal["public", "private"],
    ) -> None:
        super().__init__(
            list_skills=self._list_handler,
            get_skill=self._get_handler,
            read_directory=self._read_directory_handler if directories is not None else None,
        )
        self._catalog_skills = tuple(skills)
        self._by_uri = {skill.uri: skill for skill in skills}
        self._files = dict(files)
        self._directories = directories
        self._ttl_ms = ttl_ms
        self._cache_scope: Literal["public", "private"] = cache_scope

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
    ) -> SkillCatalog:
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

        Raises:
            ValueError: If `strict` is set and any skill is invalid, or if the provider
                lists a path that is empty, absolute, contains a `.` or `..` segment, or
                appears twice.
            OSError: If the provider fails to list or read a file.
        """
        paths = _check_paths(await provider.list_files())
        visible = [path for path in paths if not any(segment.startswith(".") for segment in path.split("/"))]
        skill_paths = sorted(path for path in visible if path.split("/")[-1] == _SKILL_FILE)

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
        )

    @property
    def skills(self) -> Sequence[Skill]:
        """The valid skills, sorted by URI."""
        return self._catalog_skills

    def resources(self) -> Sequence[ResourceBinding]:
        """One binding per served file, sorted by URI."""
        return [ResourceBinding(resource=file) for file in sorted(self._files.values(), key=lambda f: f.uri)]

    async def _list_handler(self, ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
        _reject_cursor(params.cursor)
        return ListSkillsResult(skills=list(self._catalog_skills), ttl_ms=self._ttl_ms, cache_scope=self._cache_scope)

    async def _get_handler(self, ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> GetSkillResult:
        skill = self._by_uri.get(params.uri)
        if skill is None:
            raise MCPError(code=INVALID_PARAMS, message=f"unknown skill: {params.uri}")
        return GetSkillResult(skill=skill, ttl_ms=self._ttl_ms, cache_scope=self._cache_scope)

    async def _read_directory_handler(
        self, ctx: ServerRequestContext[Any, Any], params: ReadDirectoryParams
    ) -> ReadDirectoryResult:
        assert self._directories is not None
        _reject_cursor(params.cursor)
        children = self._directories.get(params.uri)
        if children is None:
            raise MCPError(code=INVALID_PARAMS, message=f"unknown directory: {params.uri}")
        return ReadDirectoryResult(resources=list(children), ttl_ms=self._ttl_ms, cache_scope=self._cache_scope)


def _reject_cursor(cursor: str | None) -> None:
    # The catalog returns everything on one page, so it never issues a cursor.
    if cursor is not None:
        raise MCPError(code=INVALID_PARAMS, message="this server does not paginate; unexpected cursor")


def _check_paths(paths: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    for path in paths:
        if any(segment in ("", ".", "..") for segment in path.split("/")):
            raise ValueError(f"provider listed an invalid path {path!r}")
        if path in seen:
            raise ValueError(f"provider listed {path!r} more than once")
        seen.add(path)
    return list(paths)


def _fingerprint(data: bytes) -> _Fingerprint:
    return _Fingerprint(digest=hashlib.sha256(data).hexdigest(), size=len(data))


async def _load_skill(
    provider: SkillProvider,
    parse_frontmatter: Callable[[str], Mapping[str, Any]],
    skill_path: str,
    skill_md: bytes,
    visible: Sequence[str],
    fingerprints: dict[str, _Fingerprint],
) -> tuple[Skill, list[str]]:
    """Build the `Skill` whose `SKILL.md` is `skill_path`, along with the paths of its files.

    Raises:
        ValueError: If the skill is not valid.
    """
    frontmatter = _parse_frontmatter(skill_md, parse_frontmatter)
    root = skill_path.removesuffix(_SKILL_FILE)
    skill_files = [path for path in visible if path.startswith(root)]
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
    if not _is_str_mapping(parsed):
        raise ValueError("frontmatter must be a mapping with string keys")
    try:
        return to_jsonable_python(parsed)
    except ValueError as exc:
        raise ValueError(f"frontmatter is not JSON-serializable: {exc}") from exc


def _is_str_mapping(value: object) -> bool:
    return isinstance(value, Mapping) and all(isinstance(key, str) for key in cast(Mapping[object, object], value))


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


def _guess_mime_types(paths: Sequence[str]) -> dict[str, str]:
    return {
        path: "text/markdown"
        if path.split("/")[-1] == _SKILL_FILE
        else mimetypes.guess_type(path)[0] or "application/octet-stream"
        for path in paths
    }


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
