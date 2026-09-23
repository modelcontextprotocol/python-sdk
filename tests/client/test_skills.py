"""Tests for the client-side Skills extension (SEP-2640, `mcp.client.skills`)."""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp_types import INVALID_PARAMS, Resource, TextResourceContents

from mcp.client.client import Client
from mcp.client.skills import BoundSkills, verify_skill_resource
from mcp.client.skills import Skills as ClientSkills
from mcp.server.context import ServerRequestContext
from mcp.server.extension import Extension, MethodBinding
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.resources import TextResource
from mcp.server.skills import Skills
from mcp.shared.exceptions import MCPError
from mcp.shared.skills import (
    EXTENSION_ID,
    METHOD_GET,
    GetSkillParams,
    GetSkillResult,
    ListSkillsParams,
    ListSkillsResult,
    ReadDirectoryParams,
    ReadDirectoryResult,
    Skill,
    SkillResource,
)

pytestmark = pytest.mark.anyio

_SKILL_URI = "skill://git-workflow/SKILL.md"
_SKILL_CONTENT = "# git-workflow\n"
_SKILL_DIGEST = f"sha256:{hashlib.sha256(_SKILL_CONTENT.encode()).hexdigest()}"


def _skill() -> Skill:
    return Skill(
        uri=_SKILL_URI,
        frontmatter={"name": "git-workflow", "description": "d"},
        resources=[SkillResource(uri=_SKILL_URI, digest=_SKILL_DIGEST, size=len(_SKILL_CONTENT))],
    )


async def _get_skill(ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> GetSkillResult:
    if params.uri != _SKILL_URI:
        raise MCPError(code=INVALID_PARAMS, message="unknown skill")
    return GetSkillResult(skill=_skill())


def _paginated_list_handler() -> Any:
    """A `list_skills` handler serving two skills across two pages, by URI order."""
    pages = {
        None: ([_skill()], "page-2"),
        "page-2": (
            [
                Skill(
                    uri="skill://other/SKILL.md", frontmatter={"name": "other", "description": "d"}, resources="dynamic"
                )
            ],
            None,
        ),
    }

    async def handler(ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
        skills, next_cursor = pages[params.cursor]
        return ListSkillsResult(skills=skills, next_cursor=next_cursor)

    return handler


def _repeating_cursor_list_handler() -> Any:
    async def handler(ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
        return ListSkillsResult(skills=[_skill()], next_cursor="same-cursor-forever")

    return handler


class _NonConformantGetSkill(Extension):
    """A server that advertises the extension but answers `skills/get` with the wrong skill -
    the case the SDK's own `Skills` extension already rules out server-side, so this
    exercises `mcp.client.skills.get_skill`'s own defense-in-depth check."""

    identifier = EXTENSION_ID

    def methods(self) -> Any:
        async def handler(ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> GetSkillResult:
            return GetSkillResult(skill=_skill())

        return [MethodBinding(METHOD_GET, GetSkillParams, handler)]


def _repeating_cursor_directory_handler() -> Any:
    async def handler(ctx: ServerRequestContext[Any, Any], params: ReadDirectoryParams) -> ReadDirectoryResult:
        return ReadDirectoryResult(
            resources=[Resource(uri="skill://git-workflow/references/A.md", name="A.md")],
            next_cursor="same-cursor-forever",
        )

    return handler


def _paginated_directory_handler() -> Any:
    pages = {
        None: (
            [Resource(uri="skill://git-workflow/references/A.md", name="A.md")],
            "page-2",
        ),
        "page-2": (
            [Resource(uri="skill://git-workflow/references/B.md", name="B.md")],
            None,
        ),
    }

    async def handler(ctx: ServerRequestContext[Any, Any], params: ReadDirectoryParams) -> ReadDirectoryResult:
        resources, next_cursor = pages[params.cursor]
        return ReadDirectoryResult(resources=resources, next_cursor=next_cursor)

    return handler


def _server(*, with_directory_read: bool = False) -> MCPServer:
    server = MCPServer(
        "catalog",
        extensions=[
            Skills(
                list_skills=_paginated_list_handler(),
                get_skill=_get_skill,
                read_directory=_paginated_directory_handler() if with_directory_read else None,
            )
        ],
    )
    server.add_resource(TextResource(uri=_SKILL_URI, name="SKILL.md", text=_SKILL_CONTENT))
    return server


@asynccontextmanager
async def _skills(server: MCPServer) -> AsyncIterator[BoundSkills]:
    """Register the client `Skills` extension, connect, and yield the bound verbs."""
    extension = ClientSkills()
    async with Client(server, extensions=[extension]) as client:
        yield extension.bind(client)


async def test_list_skills_follows_next_cursor_to_completion() -> None:
    async with _skills(_server()) as skills:
        result = await skills.list_skills()
    assert [s.uri for s in result] == [_SKILL_URI, "skill://other/SKILL.md"]


async def test_list_skills_raises_on_a_server_that_repeats_its_cursor() -> None:
    server = MCPServer(
        "catalog", extensions=[Skills(list_skills=_repeating_cursor_list_handler(), get_skill=_get_skill)]
    )
    async with _skills(server) as skills:
        with pytest.raises(ValueError, match="repeated"):
            await skills.list_skills()


async def test_list_skills_requires_the_extension_to_be_advertised() -> None:
    """No `Skills` extension at all: the server never advertises `io.modelcontextprotocol/skills`."""
    async with _skills(MCPServer("plain")) as skills:
        with pytest.raises(ValueError, match="does not advertise"):
            await skills.list_skills()


async def test_get_skill_returns_the_matching_entry() -> None:
    async with _skills(_server()) as skills:
        skill = await skills.get_skill(_SKILL_URI)
    assert skill.uri == _SKILL_URI


async def test_get_skill_propagates_the_servers_unknown_skill_error() -> None:
    async with _skills(_server()) as skills:
        with pytest.raises(MCPError) as exc_info:
            await skills.get_skill("skill://missing/SKILL.md")
    assert exc_info.value.code == INVALID_PARAMS


async def test_read_skill_uri_reads_the_registered_resource() -> None:
    async with _skills(_server()) as skills:
        result = await skills.read_skill_uri(_SKILL_URI)
    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    assert contents.text == _SKILL_CONTENT


async def test_read_skill_uri_content_verifies_against_the_held_skill() -> None:
    """End-to-end: `skills/get`'s digest and `resources/read`'s bytes agree."""
    async with _skills(_server()) as skills:
        skill = await skills.get_skill(_SKILL_URI)
        result = await skills.read_skill_uri(_SKILL_URI)
    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    verify_skill_resource(skill, _SKILL_URI, contents.text.encode())


async def test_read_directory_follows_next_cursor_to_completion() -> None:
    async with _skills(_server(with_directory_read=True)) as skills:
        resources = await skills.read_directory("skill://git-workflow/references")
    assert [r.uri for r in resources] == [
        "skill://git-workflow/references/A.md",
        "skill://git-workflow/references/B.md",
    ]


async def test_read_directory_requires_the_directory_read_setting() -> None:
    """The extension is advertised, but without `directoryRead: true`."""
    async with _skills(_server(with_directory_read=False)) as skills:
        with pytest.raises(ValueError, match="directoryRead"):
            await skills.read_directory("skill://git-workflow/references")


async def test_read_directory_raises_on_a_server_that_repeats_its_cursor() -> None:
    server = MCPServer(
        "catalog",
        extensions=[
            Skills(
                list_skills=_paginated_list_handler(),
                get_skill=_get_skill,
                read_directory=_repeating_cursor_directory_handler(),
            )
        ],
    )
    async with _skills(server) as skills:
        with pytest.raises(ValueError, match="repeated"):
            await skills.read_directory("skill://git-workflow/references")


async def test_get_skill_rejects_a_mismatched_uri_from_a_non_conformant_server() -> None:
    server = MCPServer("catalog", extensions=[_NonConformantGetSkill()])
    async with _skills(server) as skills:
        with pytest.raises(ValueError, match="returned skill"):
            await skills.get_skill("skill://other/SKILL.md")


async def test_get_skill_round_trips_a_dynamic_skill() -> None:
    """SEP-2640 Resources: the `"dynamic"` marker survives the full server -> wire -> client
    path — validated on both ends — with the union type intact, not coerced to a list or null."""
    dynamic = Skill(
        uri="skill://generated/SKILL.md",
        frontmatter={"name": "generated", "description": "instructions generated on demand"},
        resources="dynamic",
    )

    async def get_dynamic(ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> GetSkillResult:
        # The server's own _handle_get already enforces the requested-uri match; this test only
        # ever asks for `dynamic.uri`, so the handler just returns it.
        return GetSkillResult(skill=dynamic)

    server = MCPServer("catalog", extensions=[Skills(list_skills=_paginated_list_handler(), get_skill=get_dynamic)])
    async with _skills(server) as skills:
        skill = await skills.get_skill(dynamic.uri)
    assert skill.resources == "dynamic"
    assert skill.frontmatter["name"] == "generated"


async def test_list_skills_starts_from_a_caller_supplied_cursor() -> None:
    """A host resuming from a saved cursor: `list_skills` begins at that cursor rather than the
    top, so only the pages after it come back (here, page 1's skill is skipped)."""
    async with _skills(_server()) as skills:
        result = await skills.list_skills(ListSkillsParams(cursor="page-2"))
    assert [s.uri for s in result] == ["skill://other/SKILL.md"]


async def test_list_skills_detects_a_server_repeating_the_caller_supplied_cursor() -> None:
    """The starting cursor seeds the seen-cursor set: a server that hands back the very cursor
    the caller resumed from is caught as a repeat on the first page, not chased a second time."""
    calls = 0

    async def handler(ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
        nonlocal calls
        calls += 1
        return ListSkillsResult(skills=[_skill()], next_cursor="resume-here")

    server = MCPServer("catalog", extensions=[Skills(list_skills=handler, get_skill=_get_skill)])
    async with _skills(server) as skills:
        with pytest.raises(ValueError, match="repeated"):
            await skills.list_skills(ListSkillsParams(cursor="resume-here"))
    assert calls == 1


async def test_list_skills_threads_request_meta_onto_every_page() -> None:
    """A caller-supplied `_meta` rides along with each page request, not just the first."""
    seen_meta: list[Any] = []

    async def handler(ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
        seen_meta.append(params.meta)
        if params.cursor is None:
            return ListSkillsResult(skills=[_skill()], next_cursor="page-2")
        return ListSkillsResult(
            skills=[
                Skill(
                    uri="skill://other/SKILL.md", frontmatter={"name": "other", "description": "d"}, resources="dynamic"
                )
            ],
            next_cursor=None,
        )

    server = MCPServer("catalog", extensions=[Skills(list_skills=handler, get_skill=_get_skill)])
    async with _skills(server) as skills:
        params = ListSkillsParams.model_validate({"_meta": {"progressToken": "t"}})
        await skills.list_skills(params)
    # `_meta` crosses the wire camelCase (`progressToken`), but the server deserializes it back
    # through the meta model, which exposes the known field snake_case as `progress_token`; the
    # transport also enriches `_meta` with its own keys. What matters is the caller's token
    # reaching the server on both the first page and the cursor-following second one.
    assert len(seen_meta) == 2
    assert all(m is not None and m.get("progress_token") == "t" for m in seen_meta)
