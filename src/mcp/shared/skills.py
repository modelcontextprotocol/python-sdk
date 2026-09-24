"""Wire types and SEP-2640 conformance checks for the Skills extension.

Shared by the server (`mcp.server.skills`) and client (`mcp.client.skills`)
surfaces, mirroring how `mcp.shared.extension` hosts the identifier grammar
both tiers need. See https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2640.
"""

from __future__ import annotations

import hashlib
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from mcp_types import CacheableResult, PaginatedRequestParams, PaginatedResult, Request, RequestParams, Resource
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

__all__ = [
    "EXTENSION_ID",
    "METHOD_LIST",
    "METHOD_GET",
    "METHOD_READ_DIRECTORY",
    "MAX_RESOURCES_PER_SKILL",
    "MAX_TOTAL_SIZE",
    "Frontmatter",
    "SkillResource",
    "SkillResources",
    "Skill",
    "ListSkillsParams",
    "ListSkillsResult",
    "GetSkillParams",
    "GetSkillResult",
    "ReadDirectoryParams",
    "ReadDirectoryResult",
    "ListSkillsRequest",
    "GetSkillRequest",
    "ReadDirectoryRequest",
    "skill_name_from_uri",
    "parse_directory_uri",
    "validate_directory_result",
    "verify_skill_resource",
]

EXTENSION_ID = "io.modelcontextprotocol/skills"
"""The Skills extension identifier, advertised under `ServerCapabilities.extensions`."""

METHOD_LIST = "skills/list"
METHOD_GET = "skills/get"
METHOD_READ_DIRECTORY = "resources/directory/read"

MAX_RESOURCES_PER_SKILL = 512
"""SEP-2640 per-skill resource-count threshold (`SKILL.md` included).

A SHOULD NOT limit, not a hard cap: the spec requires a host to support skills
*up to and including* 512 entries and permits it to support larger ones, so a
`Skill` does not reject an over-count manifest."""

MAX_TOTAL_SIZE = 16 * 1024 * 1024
"""SEP-2640 per-skill total-byte-size threshold (16 MiB), summed over `resources[].size`.

A SHOULD NOT limit, not a hard cap (see `MAX_RESOURCES_PER_SKILL`); an over-size
manifest is not rejected."""

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _check_digest(value: str) -> str:
    if not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"invalid SHA-256 digest {value!r}; expected 'sha256:' + 64 lowercase hex characters")
    return value


class _SkillModel(BaseModel):
    """Base for Skills value types: matches `mcp_types`' internal `MCPModel` config.

    `MCPModel` itself isn't public; every field defined below is already a
    single word, so this only matters if a future field needs camelCase.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SkillResource(_SkillModel):
    """One file in a skill's manifest: `{uri, digest, size}`.

    Shape rules are intrinsic: a `digest` that isn't `sha256:` + 64 lowercase
    hex characters, or a negative `size`, is rejected at construction.
    """

    uri: str
    digest: Annotated[str, AfterValidator(_check_digest)]
    """SHA-256 digest of the file's raw bytes, formatted `sha256:{64 hex chars}`."""
    size: Annotated[int, Field(ge=0)]
    """Length in bytes of the file's raw content."""


Frontmatter = dict[str, Any]
"""A skill's `SKILL.md` YAML frontmatter, rendered verbatim as JSON."""

SkillResources = list[SkillResource] | Literal["dynamic"]
"""A skill's complete resource manifest, or the `"dynamic"` marker (SEP-2640 Resources)."""


class Skill(_SkillModel):
    """An entry returned by `skills/list` or `skills/get`.

    SEP-2640 conformance is intrinsic: constructing (or parsing) a `Skill`
    validates the frontmatter `name`/`description`, and — unless `resources` is
    `"dynamic"` — that every entry names a file within the skill's own directory,
    with no duplicates and `SKILL.md` present. The `MAX_RESOURCES_PER_SKILL`
    (512-entry) and `MAX_TOTAL_SIZE` (16-MiB) limits are SHOULD NOT thresholds,
    not MUST NOT, so an over-limit manifest is accepted.
    """

    uri: str
    """Resource URI of the skill's `SKILL.md`."""
    frontmatter: Frontmatter
    resources: SkillResources

    @model_validator(mode="after")
    def _check_conformance(self) -> Skill:
        name = skill_name_from_uri(self.uri)
        frontmatter_name = self.frontmatter.get("name")
        if (
            not isinstance(frontmatter_name, str)
            or not _NAME_RE.fullmatch(frontmatter_name)
            or len(frontmatter_name) > 64
        ):
            raise ValueError(f"skill {self.uri!r} frontmatter name must be 1-64 lowercase, digits, or hyphens")
        if frontmatter_name != name:
            raise ValueError(
                f"skill {self.uri!r} frontmatter name {frontmatter_name!r} does not match URI name {name!r}"
            )
        description = self.frontmatter.get("description")
        if not isinstance(description, str) or not (1 <= len(description) <= 1024):
            raise ValueError(f"skill {self.uri!r} frontmatter description must contain 1 to 1024 characters")
        if self.resources == "dynamic":
            return self
        seen: set[str] = set()
        for resource in self.resources:
            _validate_resource_uri_in_skill(self.uri, resource.uri)
            if resource.uri in seen:
                raise ValueError(f"skill {self.uri!r} lists resource {resource.uri!r} more than once")
            seen.add(resource.uri)
        if self.uri not in seen:
            raise ValueError(f"skill {self.uri!r} resources does not include its own SKILL.md")
        return self


class ListSkillsParams(PaginatedRequestParams):
    """Parameters for `skills/list`."""


class ListSkillsResult(PaginatedResult, CacheableResult):
    """Result of `skills/list`.

    Each skill self-validates; on top of that, constructing (or parsing) this
    result rejects two entries that share a `uri`.

    `ttl_ms`/`cache_scope` are SEP-2549 fields inherited from `CacheableResult`;
    unlike a core spec method, nothing sieves them off the wire for a
    pre-2026-07-28 connection automatically (see `mcp.server.skills`), so
    callers constructing this directly for such a connection must omit them.
    """

    skills: list[Skill]

    @model_validator(mode="after")
    def _check_unique_uris(self) -> ListSkillsResult:
        seen: set[str] = set()
        for skill in self.skills:
            if skill.uri in seen:
                raise ValueError(f"skills/list result lists skill {skill.uri!r} more than once")
            seen.add(skill.uri)
        return self


class GetSkillParams(RequestParams):
    """Parameters for `skills/get`."""

    uri: str
    """URI of the skill's `SKILL.md`."""


class GetSkillResult(CacheableResult):
    """Result of `skills/get`.

    Like `ListSkillsResult`, this extends `CacheableResult`: the stable spec page
    makes `GetSkillResult` carry SEP-2549's `ttl_ms`/`cache_scope`, the same
    freshness hint `resources/read` gives. As on `skills/list`, nothing sieves
    these fields off the wire for a pre-2026-07-28 connection automatically (see
    `mcp.server.skills`), so a caller constructing this directly for such a
    connection must omit them.
    """

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
    """Validate that each entry in `result.resources` is a unique direct child of `uri`.

    Checks containment and shape only — that every listed resource is a direct
    child of `uri` with a unique `uri` and `name`. It cannot confirm the listing
    is exhaustive, since it has no independent view of the directory's contents.

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
    """Check that `content` (the bytes read from `uri`) matches `skill`'s manifest entry.

    Recomputes the size and SHA-256 digest of `content` and compares them to the
    entry `skill` holds for `uri` — the byte-integrity check SEP-2640 requires
    before a host trusts a fetched file. A `"dynamic"` skill carries no digests,
    so it has nothing to verify against.

    Raises:
        ValueError: If `uri` is not one of `skill`'s resources, `skill.resources`
            is `"dynamic"`, or `content`'s size or digest doesn't match the entry.
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
