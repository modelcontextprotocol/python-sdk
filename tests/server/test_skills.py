"""Tests for the Skills extension (`io.modelcontextprotocol/skills`, SEP-2640).

`mcp.shared.skills`'s validators are unit-tested in `tests/shared/test_skills.py`; this
file covers this module's own wiring: request dispatch, capability advertisement, the
`skills/get`/`resources/directory/read` URI checks the extension performs itself before
calling the handler, and — the one piece of SEP-2549 behavior a hand-rolled extension
method must implement itself — gating `ttlMs`/`cacheScope` to protocol version 2026-07-28+.
"""

from typing import Any

import pytest
from inline_snapshot import snapshot
from mcp_types import INTERNAL_ERROR, INVALID_PARAMS, METHOD_NOT_FOUND, Resource
from pydantic import BaseModel, ConfigDict

from mcp.client.client import Client
from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.skills import Skills
from mcp.shared.exceptions import MCPError
from mcp.shared.skills import (
    GetSkillParams,
    GetSkillRequest,
    GetSkillResult,
    ListSkillsParams,
    ListSkillsRequest,
    ListSkillsResult,
    ReadDirectoryParams,
    ReadDirectoryRequest,
    ReadDirectoryResult,
    Skill,
    SkillResource,
)

pytestmark = pytest.mark.anyio


class _RawResult(BaseModel):
    """Captures every wire field, typed, so assertions can inspect fields our own
    `ListSkillsResult` model doesn't declare being absent (there are none) or present."""

    model_config = ConfigDict(extra="allow")


_DIGEST = "sha256:" + "a" * 64
_SKILL_URI = "skill://git-workflow/SKILL.md"


def _git_workflow_skill() -> Skill:
    return Skill(
        uri=_SKILL_URI,
        frontmatter={"name": "git-workflow", "description": "Follow this team's Git conventions"},
        resources=[SkillResource(uri=_SKILL_URI, digest=_DIGEST, size=10)],
    )


async def _list_skills(ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
    return ListSkillsResult(skills=[_git_workflow_skill()])


async def _get_skill(ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> GetSkillResult:
    if params.uri != _SKILL_URI:
        raise MCPError(code=INVALID_PARAMS, message="unknown skill")
    return GetSkillResult(skill=_git_workflow_skill())


async def _read_directory(ctx: ServerRequestContext[Any, Any], params: ReadDirectoryParams) -> ReadDirectoryResult:
    return ReadDirectoryResult(
        resources=[Resource(uri="skill://git-workflow/references", name="references", mime_type="inode/directory")]
    )


def _server(*, with_directory_read: bool = False) -> MCPServer:
    return MCPServer(
        "catalog",
        extensions=[
            Skills(
                list_skills=_list_skills,
                get_skill=_get_skill,
                read_directory=_read_directory if with_directory_read else None,
            )
        ],
    )


async def test_skills_list_returns_the_handlers_skills() -> None:
    async with Client(_server(), mode="2026-07-28") as client:
        result = await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
    assert [s.uri for s in result.skills] == [_SKILL_URI]


async def test_skills_list_may_return_an_empty_result() -> None:
    """SEP-2640 Enumeration: the result MAY be empty."""

    async def empty(ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
        return ListSkillsResult(skills=[])

    server = MCPServer("catalog", extensions=[Skills(list_skills=empty, get_skill=_get_skill)])
    async with Client(server, mode="2026-07-28") as client:
        result = await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
    assert result.skills == []


async def test_skills_list_carries_cache_fields_on_the_2026_07_28_wire() -> None:
    """SEP-2640 Dependencies: on 2026-07-28+, the result carries the SEP-2549 cache fields,
    defaulting `cacheScope` to `"public"` when the handler left it unset."""
    async with Client(_server(), mode="2026-07-28") as client:
        raw = await client.session.send_request(ListSkillsRequest(), _RawResult)
    extra = raw.model_extra or {}
    assert extra["cacheScope"] == "public"
    assert extra["ttlMs"] == 0


async def test_skills_list_omits_cache_fields_on_a_legacy_wire() -> None:
    """The runner's per-version sieve only applies to core spec methods, so this extension
    method must strip SEP-2549 fields itself for a pre-2026-07-28 connection."""
    async with Client(_server(), mode="legacy") as client:
        raw = await client.session.send_request(ListSkillsRequest(), _RawResult)
    extra = raw.model_extra or {}
    assert "cacheScope" not in extra
    assert "ttlMs" not in extra


async def test_skills_list_handler_setting_cache_scope_explicitly_is_not_overridden() -> None:
    async def private_list(ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
        return ListSkillsResult(skills=[_git_workflow_skill()], cache_scope="private")

    server = MCPServer("catalog", extensions=[Skills(list_skills=private_list, get_skill=_get_skill)])
    async with Client(server, mode="2026-07-28") as client:
        raw = await client.session.send_request(ListSkillsRequest(), _RawResult)
    extra = raw.model_extra or {}
    assert extra["cacheScope"] == "private"


async def test_skills_list_rejects_a_handler_result_with_an_invalid_skill() -> None:
    """SDK-defined: a `list_skills` handler bug (a non-conformant skill entry) is caught
    before it reaches the client, as an Internal error — the fault is the server's, not the
    caller's params — rather than a silently non-conformant listing."""

    async def bad_list(ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
        return ListSkillsResult(
            skills=[Skill(uri=_SKILL_URI, frontmatter={"name": "git-workflow", "description": "d"}, resources=[])]
        )

    server = MCPServer("catalog", extensions=[Skills(list_skills=bad_list, get_skill=_get_skill)])
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
    assert exc_info.value.code == INTERNAL_ERROR


async def test_skills_get_returns_the_matching_skill() -> None:
    async with Client(_server()) as client:
        result = await client.session.send_request(
            GetSkillRequest(params=GetSkillParams(uri=_SKILL_URI)), GetSkillResult
        )
    assert result.skill.uri == _SKILL_URI


async def test_skills_get_carries_cache_fields_on_the_2026_07_28_wire() -> None:
    """SEP-2640 Retrieval: on 2026-07-28+, `GetSkillResult` extends `CacheableResult`, so the
    result carries the SEP-2549 cache fields, defaulting `cacheScope` to `"public"` when unset —
    the same treatment `skills/list` gets."""
    async with Client(_server(), mode="2026-07-28") as client:
        raw = await client.session.send_request(GetSkillRequest(params=GetSkillParams(uri=_SKILL_URI)), _RawResult)
    extra = raw.model_extra or {}
    assert extra["cacheScope"] == "public"
    assert extra["ttlMs"] == 0


async def test_skills_get_omits_cache_fields_on_a_legacy_wire() -> None:
    """As with `skills/list`, this extension method strips the SEP-2549 fields itself for a
    pre-2026-07-28 connection, since the runner's per-version sieve only applies to core methods."""
    async with Client(_server(), mode="legacy") as client:
        raw = await client.session.send_request(GetSkillRequest(params=GetSkillParams(uri=_SKILL_URI)), _RawResult)
    extra = raw.model_extra or {}
    assert "cacheScope" not in extra
    assert "ttlMs" not in extra


async def test_skills_get_answers_for_a_skill_absent_from_the_listing() -> None:
    """SEP-2640 Retrieval: a server MUST answer for every skill it serves, whether or not
    that skill appears in `skills/list`."""

    async def list_without_it(ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
        return ListSkillsResult(skills=[])

    server = MCPServer("catalog", extensions=[Skills(list_skills=list_without_it, get_skill=_get_skill)])
    async with Client(server) as client:
        listing = await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
        result = await client.session.send_request(
            GetSkillRequest(params=GetSkillParams(uri=_SKILL_URI)), GetSkillResult
        )
    assert listing.skills == []
    assert result.skill.uri == _SKILL_URI


async def test_skills_get_rejects_an_unknown_uri_with_invalid_params() -> None:
    """SEP-2640 Retrieval: an unknown skill URI MUST be rejected with -32602 (Invalid params)."""
    async with Client(_server()) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                GetSkillRequest(params=GetSkillParams(uri="skill://other/SKILL.md")), GetSkillResult
            )
    assert exc_info.value.code == INVALID_PARAMS


async def test_skills_get_rejects_a_uri_that_does_not_end_in_skill_md() -> None:
    async with Client(_server()) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                GetSkillRequest(params=GetSkillParams(uri="skill://git-workflow/README.md")), GetSkillResult
            )
    assert exc_info.value.code == INVALID_PARAMS


async def test_skills_get_rejects_a_handler_that_returns_a_mismatched_uri() -> None:
    """SDK-defined: a `get_skill` handler bug (returning the wrong skill) is caught before
    it reaches the client, as an Internal error rather than a silently wrong answer."""

    async def wrong_skill(ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> GetSkillResult:
        return GetSkillResult(skill=_git_workflow_skill())

    server = MCPServer("catalog", extensions=[Skills(list_skills=_list_skills, get_skill=wrong_skill)])
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                GetSkillRequest(params=GetSkillParams(uri="skill://other/SKILL.md")), GetSkillResult
            )
    assert exc_info.value.code == INTERNAL_ERROR


async def test_skills_get_rejects_a_matching_but_non_conformant_skill() -> None:
    """SDK-defined: a `get_skill` handler bug (a non-conformant skill body, distinct from a
    URI mismatch) is caught the same way, as an Internal error."""

    async def bad_skill(ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> GetSkillResult:
        return GetSkillResult(
            skill=Skill(uri=params.uri, frontmatter={"name": "git-workflow", "description": "d"}, resources=[])
        )

    server = MCPServer("catalog", extensions=[Skills(list_skills=_list_skills, get_skill=bad_skill)])
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(GetSkillRequest(params=GetSkillParams(uri=_SKILL_URI)), GetSkillResult)
    assert exc_info.value.code == INTERNAL_ERROR


async def test_missing_uri_param_is_rejected_before_the_handler_runs() -> None:
    """SDK-defined: `uri` is a required field on `GetSkillParams`, so an omitted param is
    rejected by params validation - the handler never sees it."""
    async with Client(_server()) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(GetSkillRequest.model_construct(params=None), GetSkillResult)
    assert exc_info.value.code == INVALID_PARAMS


async def test_directory_read_is_not_advertised_without_a_handler() -> None:
    async with Client(_server(with_directory_read=False)) as client:
        assert client.server_capabilities.extensions == {"io.modelcontextprotocol/skills": {}}


async def test_directory_read_is_advertised_when_a_handler_is_supplied() -> None:
    async with Client(_server(with_directory_read=True)) as client:
        assert client.server_capabilities.extensions == snapshot(
            {"io.modelcontextprotocol/skills": {"directoryRead": True}}
        )


async def test_directory_read_returns_the_handlers_children() -> None:
    async with Client(_server(with_directory_read=True)) as client:
        result = await client.session.send_request(
            ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://git-workflow")), ReadDirectoryResult
        )
    assert [r.uri for r in result.resources] == ["skill://git-workflow/references"]


async def test_directory_read_is_not_registered_without_a_handler() -> None:
    """SDK-defined: omitting `read_directory` doesn't just skip the capability ad - the
    method itself isn't registered, so calling it anyway is Method not found."""
    async with Client(_server(with_directory_read=False)) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://git-workflow")), ReadDirectoryResult
            )
    assert exc_info.value.code == METHOD_NOT_FOUND


async def test_directory_read_rejects_a_trailing_slash_uri() -> None:
    """SEP-2640 Directory resources: directory URIs are written without a trailing slash."""
    async with Client(_server(with_directory_read=True)) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://git-workflow/")), ReadDirectoryResult
            )
    assert exc_info.value.code == INVALID_PARAMS


async def test_directory_read_rejects_a_handler_result_with_a_grandchild() -> None:
    """SDK-defined: a `read_directory` handler bug (a non-direct child) is a server fault,
    surfaced as an Internal error, not the caller's Invalid params."""

    async def bad_directory(ctx: ServerRequestContext[Any, Any], params: ReadDirectoryParams) -> ReadDirectoryResult:
        return ReadDirectoryResult(resources=[Resource(uri="skill://git-workflow/a/b/c.md", name="c.md")])

    server = MCPServer(
        "catalog", extensions=[Skills(list_skills=_list_skills, get_skill=_get_skill, read_directory=bad_directory)]
    )
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://git-workflow")), ReadDirectoryResult
            )
    assert exc_info.value.code == INTERNAL_ERROR
