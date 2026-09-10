"""The Skills extension (`io.modelcontextprotocol/skills`, SEP-2640).

SEP-2640 defines a convention for serving Agent Skills over MCP using the
Resources primitive: a skill is a directory of files, conventionally exposed
under the `skill://` scheme, and enumerated and fetched through two required
methods (`skills/list`, `skills/get`) plus one optional one
(`resources/directory/read`). See
https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2640.

This module provides the protocol-level plumbing only: request/response
handling, SEP-2640 conformance validation, and capability advertisement. It
does not discover, read, or hash skills from a filesystem — a server author
supplies handlers that answer `skills/list`/`skills/get`/`resources/directory/read`
however their catalog is stored, and serves the underlying `skill://` file
content through the server's ordinary resource-registration APIs
(`MCPServer.add_resource`, or an `@mcp.resource(...)` template).

    async def list_skills(ctx, params):
        return ListSkillsResult(skills=[...])

    async def get_skill(ctx, params):
        if params.uri != "skill://git-workflow/SKILL.md":
            raise MCPError(code=INVALID_PARAMS, message="unknown skill")
        return GetSkillResult(skill=...)

    mcp = MCPServer("catalog", extensions=[Skills(list_skills=list_skills, get_skill=get_skill)])
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from mcp_types.jsonrpc import INTERNAL_ERROR, INVALID_PARAMS
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from mcp.server.context import HandlerResult, ServerRequestContext
from mcp.server.extension import Extension, MethodBinding
from mcp.shared.exceptions import MCPError
from mcp.shared.skills import (
    EXTENSION_ID,
    METHOD_GET,
    METHOD_LIST,
    METHOD_READ_DIRECTORY,
    GetSkillParams,
    GetSkillResult,
    ListSkillsParams,
    ListSkillsResult,
    ReadDirectoryParams,
    ReadDirectoryResult,
    parse_directory_uri,
    skill_name_from_uri,
    validate_directory_result,
    validate_list_result,
    validate_skill,
)

__all__ = ["Skills"]

logger = logging.getLogger(__name__)

ListSkillsHandler = Callable[[ServerRequestContext[Any, Any], ListSkillsParams], Awaitable[ListSkillsResult]]
GetSkillHandler = Callable[[ServerRequestContext[Any, Any], GetSkillParams], Awaitable[GetSkillResult]]
ReadDirectoryHandler = Callable[[ServerRequestContext[Any, Any], ReadDirectoryParams], Awaitable[ReadDirectoryResult]]


class Skills(Extension):
    """The Skills extension: serve `skills/list`, `skills/get`, and directory reads.

    `list_skills` and `get_skill` are required; a server MUST answer both per
    SEP-2640, whether or not a skill appears in the listing. `read_directory`
    is optional — supplying it advertises the `directoryRead` capability
    setting and serves `resources/directory/read`; omitting it advertises
    neither. Handlers run per request, so a catalog that changes over time
    (or is too large to enumerate) can return a partial or empty listing.
    """

    identifier = EXTENSION_ID

    def __init__(
        self,
        *,
        list_skills: ListSkillsHandler,
        get_skill: GetSkillHandler,
        read_directory: ReadDirectoryHandler | None = None,
    ) -> None:
        self._list_skills = list_skills
        self._get_skill = get_skill
        self._read_directory = read_directory

    def settings(self) -> dict[str, Any]:
        return {"directoryRead": True} if self._read_directory is not None else {}

    def methods(self) -> Sequence[MethodBinding]:
        bindings = [
            MethodBinding(METHOD_LIST, ListSkillsParams, self._handle_list),
            MethodBinding(METHOD_GET, GetSkillParams, self._handle_get),
        ]
        if self._read_directory is not None:
            bindings.append(MethodBinding(METHOD_READ_DIRECTORY, ReadDirectoryParams, self._handle_read_directory))
        return bindings

    async def _handle_list(self, ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> HandlerResult:
        result = await self._list_skills(ctx, params)
        try:
            validate_list_result(result)
        except ValueError:
            logger.exception("list_skills handler returned an invalid result")
            raise MCPError(code=INTERNAL_ERROR, message="Handler returned an invalid result") from None
        return _finalize_cacheable(result, ctx.protocol_version)

    async def _handle_get(self, ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> HandlerResult:
        _require_skill_md_uri(params.uri)
        result = await self._get_skill(ctx, params)
        if result.skill.uri != params.uri:
            logger.error("get_skill handler returned %r for requested %r", result.skill.uri, params.uri)
            raise MCPError(code=INTERNAL_ERROR, message="Handler returned an invalid result")
        try:
            validate_skill(result.skill)
        except ValueError:
            logger.exception("get_skill handler returned an invalid result")
            raise MCPError(code=INTERNAL_ERROR, message="Handler returned an invalid result") from None
        return result

    async def _handle_read_directory(
        self, ctx: ServerRequestContext[Any, Any], params: ReadDirectoryParams
    ) -> HandlerResult:
        assert self._read_directory is not None
        _require_directory_uri(params.uri)
        result = await self._read_directory(ctx, params)
        try:
            validate_directory_result(params.uri, result)
        except ValueError:
            logger.exception("read_directory handler returned an invalid result")
            raise MCPError(code=INTERNAL_ERROR, message="Handler returned an invalid result") from None
        return result


def _require_skill_md_uri(uri: str) -> None:
    try:
        skill_name_from_uri(uri)
    except ValueError as exc:
        raise MCPError(code=INVALID_PARAMS, message=str(exc)) from exc


def _require_directory_uri(uri: str) -> None:
    try:
        parse_directory_uri(uri)
    except ValueError as exc:
        raise MCPError(code=INVALID_PARAMS, message=str(exc)) from exc


def _finalize_cacheable(result: ListSkillsResult, protocol_version: str) -> HandlerResult:
    """Gate SEP-2549's `ttlMs`/`cacheScope` to protocol version 2026-07-28+.

    `skills/list` is an extension method, so — unlike a core spec method — the
    runner's per-version surface sieve never runs on its result; nothing else
    strips these fields for a legacy connection. `CacheableResult` defaults to
    `cache_scope="private"`; SEP-2640 calls for `"public"` when unset.
    """
    if protocol_version in MODERN_PROTOCOL_VERSIONS:
        if "cache_scope" not in result.model_fields_set:
            result = result.model_copy(update={"cache_scope": "public"})
        return result
    dumped = result.model_dump(by_alias=True, mode="json", exclude_none=True)
    dumped.pop("ttlMs", None)
    dumped.pop("cacheScope", None)
    return dumped
