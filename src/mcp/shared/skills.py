"""Wire types and SEP-2640 conformance checks for the Skills extension.

Shared by the server (`mcp.server.skills`) and client (`mcp.client.skills`)
surfaces, mirroring how `mcp.shared.extension` hosts the identifier grammar
both tiers need. See https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2640.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal
from urllib.parse import urlsplit

from mcp_types import CacheableResult, PaginatedRequestParams, PaginatedResult, Request, RequestParams, Resource, Result
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

EXTENSION_ID = "io.modelcontextprotocol/skills"
"""The Skills extension identifier, advertised under `ServerCapabilities.extensions`."""

METHOD_LIST = "skills/list"
METHOD_GET = "skills/get"
METHOD_READ_DIRECTORY = "resources/directory/read"

MAX_RESOURCES_PER_SKILL = 512
"""SEP-2640 per-skill resource-count limit, `SKILL.md` included."""

MAX_TOTAL_SIZE = 16 * 1024 * 1024
"""SEP-2640 per-skill total-byte-size limit (16 MiB), summed over `resources[].size`."""

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class _SkillModel(BaseModel):
    """Base for Skills value types: matches `mcp_types`' internal `MCPModel` config.

    `MCPModel` itself isn't public; every field defined below is already a
    single word, so this only matters if a future field needs camelCase.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SkillResource(_SkillModel):
    """One file in a skill's manifest: `{uri, digest, size}`."""

    uri: str
    digest: str
    """SHA-256 digest of the file's raw bytes, formatted `sha256:{64 hex chars}`."""
    size: int
    """Length in bytes of the file's raw content."""


Frontmatter = dict[str, Any]
"""A skill's `SKILL.md` YAML frontmatter, rendered verbatim as JSON."""

SkillResources = list[SkillResource] | Literal["dynamic"]
"""A skill's complete resource manifest, or the `"dynamic"` marker (SEP-2640 Resources)."""


class Skill(_SkillModel):
    """An entry returned by `skills/list` or `skills/get`."""

    uri: str
    """Resource URI of the skill's `SKILL.md`."""
    frontmatter: Frontmatter
    resources: SkillResources


class ListSkillsParams(PaginatedRequestParams):
    """Parameters for `skills/list`."""


class ListSkillsResult(PaginatedResult, CacheableResult):
    """Result of `skills/list`.

    `ttl_ms`/`cache_scope` are SEP-2549 fields inherited from `CacheableResult`;
    unlike a core spec method, nothing sieves them off the wire for a
    pre-2026-07-28 connection automatically (see `mcp.server.skills`), so
    callers constructing this directly for such a connection must omit them.
    """

    skills: list[Skill]


class GetSkillParams(RequestParams):
    """Parameters for `skills/get`."""

    uri: str
    """URI of the skill's `SKILL.md`."""


class GetSkillResult(Result):
    """Result of `skills/get`."""

    skill: Skill


class ReadDirectoryParams(PaginatedRequestParams):
    """Parameters for `resources/directory/read`."""

    uri: str
    """URI of the directory resource whose direct children are listed."""


class ReadDirectoryResult(PaginatedResult):
    """Result of `resources/directory/read`."""

    resources: list[Resource]


class ListSkillsRequest(Request[ListSkillsParams | None, Literal["skills/list"]]):
    method: Literal["skills/list"] = "skills/list"
    params: ListSkillsParams | None = None


class GetSkillRequest(Request[GetSkillParams, Literal["skills/get"]]):
    method: Literal["skills/get"] = "skills/get"
    params: GetSkillParams


class ReadDirectoryRequest(Request[ReadDirectoryParams, Literal["resources/directory/read"]]):
    method: Literal["resources/directory/read"] = "resources/directory/read"
    params: ReadDirectoryParams


def skill_name_from_uri(uri: str) -> str:
    """Return the skill `name` encoded in a `SKILL.md` resource URI.

    Per SEP-2640 Resource Mapping, the final `<skill-path>` segment equals the
    skill's `name`; for a bare `skill://<name>/SKILL.md` (no organizational
    prefix) that segment is the authority.

    Raises:
        ValueError: If `uri` is not an absolute URI ending in `/SKILL.md`.
    """
    parts = urlsplit(uri)
    if not parts.scheme or parts.query or parts.fragment:
        raise ValueError(f"skill URI {uri!r} is not a valid absolute resource URI")
    if not parts.path.endswith("/SKILL.md"):
        raise ValueError(f"skill URI {uri!r} must end in /SKILL.md")
    directory = parts.path[: -len("/SKILL.md")].strip("/")
    if directory:
        name = directory.rsplit("/", 1)[-1]
    else:
        name = parts.hostname or ""
    if not name:
        raise ValueError(f"skill URI {uri!r} has no skill name")
    return name


def _validate_resource_uri_in_skill(skill_uri: str, resource_uri: str) -> None:
    """Raise `ValueError` unless `resource_uri` names a file within `skill_uri`'s directory."""
    skill_parts = urlsplit(skill_uri)
    resource_parts = urlsplit(resource_uri)
    if not resource_parts.scheme or resource_parts.query or resource_parts.fragment:
        raise ValueError(f"resource URI {resource_uri!r} is invalid")
    if resource_uri.endswith("/"):
        raise ValueError(f"resource URI {resource_uri!r} names a directory, not a file")
    if skill_parts.scheme != resource_parts.scheme or skill_parts.netloc != resource_parts.netloc:
        raise ValueError(f"resource URI {resource_uri!r} is outside the skill root {skill_uri!r}")
    root = skill_parts.path[: -len("/SKILL.md")]
    if resource_parts.path != skill_parts.path and not resource_parts.path.startswith(root + "/"):
        raise ValueError(f"resource URI {resource_uri!r} is outside the skill root {skill_uri!r}")
    if any(segment in (".", "..") for segment in resource_parts.path.split("/")):
        raise ValueError(f"resource URI {resource_uri!r} contains a traversal segment")


def validate_skill(skill: Skill) -> None:
    """Validate `skill` against the SEP-2640 and Agent Skills conformance rules.

    Checks the frontmatter's `name`/`description` fields, that `resources` (when
    not `"dynamic"`) is complete and within the `MAX_RESOURCES_PER_SKILL`/
    `MAX_TOTAL_SIZE` limits, and that every resource entry names a file within
    the skill's own directory with a well-formed digest.

    Raises:
        ValueError: If `skill` violates any of the above.
    """
    name = skill_name_from_uri(skill.uri)
    frontmatter_name = skill.frontmatter.get("name")
    if not isinstance(frontmatter_name, str) or not _NAME_RE.fullmatch(frontmatter_name) or len(frontmatter_name) > 64:
        raise ValueError(f"skill {skill.uri!r} frontmatter name must be 1-64 lowercase, digits, or hyphens")
    if frontmatter_name != name:
        raise ValueError(f"skill {skill.uri!r} frontmatter name {frontmatter_name!r} does not match URI name {name!r}")
    description = skill.frontmatter.get("description")
    if not isinstance(description, str) or not (1 <= len(description) <= 1024):
        raise ValueError(f"skill {skill.uri!r} frontmatter description must contain 1 to 1024 characters")

    if skill.resources == "dynamic":
        return
    resources = skill.resources
    if len(resources) > MAX_RESOURCES_PER_SKILL:
        raise ValueError(f"skill {skill.uri!r} has {len(resources)} resources, exceeding {MAX_RESOURCES_PER_SKILL}")
    seen: set[str] = set()
    total_size = 0
    for resource in resources:
        _validate_resource_uri_in_skill(skill.uri, resource.uri)
        if resource.uri in seen:
            raise ValueError(f"skill {skill.uri!r} lists resource {resource.uri!r} more than once")
        seen.add(resource.uri)
        if not _DIGEST_RE.fullmatch(resource.digest):
            raise ValueError(f"skill {skill.uri!r} resource {resource.uri!r} has an invalid SHA-256 digest")
        if resource.size < 0:
            raise ValueError(f"skill {skill.uri!r} resource {resource.uri!r} has a negative size")
        total_size += resource.size
    if skill.uri not in seen:
        raise ValueError(f"skill {skill.uri!r} resources does not include its own SKILL.md")
    if total_size > MAX_TOTAL_SIZE:
        raise ValueError(f"skill {skill.uri!r} has {total_size} bytes, exceeding {MAX_TOTAL_SIZE}")


def validate_list_result(result: ListSkillsResult) -> None:
    """Validate every skill in `result.skills` and reject duplicate URIs.

    Raises:
        ValueError: If any skill is invalid, or two entries share a `uri`.
    """
    seen: set[str] = set()
    for skill in result.skills:
        validate_skill(skill)
        if skill.uri in seen:
            raise ValueError(f"skills/list result lists skill {skill.uri!r} more than once")
        seen.add(skill.uri)


def parse_directory_uri(uri: str) -> tuple[str, str, str]:
    """Split a directory resource URI into `(scheme, netloc, path)`.

    Raises:
        ValueError: If `uri` has a trailing slash, or is otherwise not a valid
            absolute resource URI.
    """
    if uri.endswith("/"):
        raise ValueError(f"directory URI {uri!r} must not have a trailing slash")
    parts = urlsplit(uri)
    if not parts.scheme or parts.query or parts.fragment:
        raise ValueError(f"directory URI {uri!r} is not a valid absolute resource URI")
    return parts.scheme, parts.netloc, parts.path


def validate_directory_result(uri: str, result: ReadDirectoryResult) -> None:
    """Validate that `result.resources` are exactly the direct children of `uri`.

    Raises:
        ValueError: If `uri` is malformed, or any entry is not a direct child,
            or two entries share a `uri` or `name`.
    """
    scheme, netloc, parent_path = parse_directory_uri(uri)
    seen_uris: set[str] = set()
    seen_names: set[str] = set()
    prefix = parent_path.rstrip("/") + "/" if parent_path.rstrip("/") else "/"
    for resource in result.resources:
        child = urlsplit(resource.uri)
        if not child.scheme or child.query or child.fragment:
            raise ValueError(f"directory {uri!r} child has invalid URI {resource.uri!r}")
        if child.scheme != scheme or child.netloc != netloc:
            raise ValueError(f"resource {resource.uri!r} is not a child of directory {uri!r}")
        relative = child.path.removeprefix(prefix)
        if relative == child.path or not relative or "/" in relative or relative in (".", ".."):
            raise ValueError(f"resource {resource.uri!r} is not a direct child of directory {uri!r}")
        if resource.uri in seen_uris or resource.name in seen_names:
            raise ValueError(f"directory {uri!r} contains a duplicate child {resource.uri!r}")
        seen_uris.add(resource.uri)
        seen_names.add(resource.name)


def verify_skill_resource(skill: Skill, uri: str, content: bytes) -> None:
    """Verify `content` (the bytes read from `uri`) against `skill`'s held manifest.

    Implements the SEP-2640 Integrity and verification requirement: a host
    MUST verify a retrieved file's bytes against its manifest entry before
    using them. Not applicable to a skill whose `resources` is `"dynamic"`,
    which offers no digest to verify against.

    Raises:
        ValueError: If `uri` is not one of `skill`'s resources, `skill.resources`
            is `"dynamic"`, or `content` does not match the entry's `size`/`digest`.
    """
    if skill.resources == "dynamic":
        raise ValueError(f"skill {skill.uri!r} has dynamic resources and cannot be integrity-verified")
    entry = next((r for r in skill.resources if r.uri == uri), None)
    if entry is None:
        raise ValueError(f"{uri!r} is not in skill {skill.uri!r}'s held manifest")
    if len(content) != entry.size:
        raise ValueError(f"resource {uri!r} has size {len(content)}, expected {entry.size}")
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if digest != entry.digest:
        raise ValueError(f"resource {uri!r} has digest {digest!r}, expected {entry.digest!r}")
