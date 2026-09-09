"""Tests for the client-side Skills convenience wrappers (SEP-2640, `mcp.client.skills`)."""

import hashlib
from typing import Any

import pytest
from mcp_types import INVALID_PARAMS, Resource, TextResourceContents

from mcp.client.client import Client
from mcp.client.skills import get_skill, list_skills, read_directory, read_skill_uri, verify_skill_resource
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


async def test_list_skills_follows_next_cursor_to_completion() -> None:
    async with Client(_server()) as client:
        skills = await list_skills(client.session)
    assert [s.uri for s in skills] == [_SKILL_URI, "skill://other/SKILL.md"]


async def test_list_skills_raises_on_a_server_that_repeats_its_cursor() -> None:
    server = MCPServer(
        "catalog", extensions=[Skills(list_skills=_repeating_cursor_list_handler(), get_skill=_get_skill)]
    )
    async with Client(server) as client:
        with pytest.raises(ValueError, match="repeated"):
            await list_skills(client.session)


async def test_list_skills_requires_the_extension_to_be_advertised() -> None:
    """No `Skills` extension at all: the server never advertises `io.modelcontextprotocol/skills`."""
    async with Client(MCPServer("plain")) as client:
        with pytest.raises(ValueError, match="does not advertise"):
            await list_skills(client.session)


async def test_get_skill_returns_the_matching_entry() -> None:
    async with Client(_server()) as client:
        skill = await get_skill(client.session, _SKILL_URI)
    assert skill.uri == _SKILL_URI


async def test_get_skill_propagates_the_servers_unknown_skill_error() -> None:
    async with Client(_server()) as client:
        with pytest.raises(MCPError) as exc_info:
            await get_skill(client.session, "skill://missing/SKILL.md")
    assert exc_info.value.code == INVALID_PARAMS


async def test_read_skill_uri_reads_the_registered_resource() -> None:
    async with Client(_server()) as client:
        result = await read_skill_uri(client.session, _SKILL_URI)
    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    assert contents.text == _SKILL_CONTENT


async def test_read_skill_uri_content_verifies_against_the_held_skill() -> None:
    """End-to-end: `skills/get`'s digest and `resources/read`'s bytes agree."""
    async with Client(_server()) as client:
        skill = await get_skill(client.session, _SKILL_URI)
        result = await read_skill_uri(client.session, _SKILL_URI)
    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    verify_skill_resource(skill, _SKILL_URI, contents.text.encode())


async def test_read_directory_follows_next_cursor_to_completion() -> None:
    async with Client(_server(with_directory_read=True)) as client:
        resources = await read_directory(client.session, "skill://git-workflow/references")
    assert [r.uri for r in resources] == [
        "skill://git-workflow/references/A.md",
        "skill://git-workflow/references/B.md",
    ]


async def test_read_directory_requires_the_directory_read_setting() -> None:
    """The extension is advertised, but without `directoryRead: true`."""
    async with Client(_server(with_directory_read=False)) as client:
        with pytest.raises(ValueError, match="directoryRead"):
            await read_directory(client.session, "skill://git-workflow/references")


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
    async with Client(server) as client:
        with pytest.raises(ValueError, match="repeated"):
            await read_directory(client.session, "skill://git-workflow/references")


async def test_get_skill_rejects_a_mismatched_uri_from_a_non_conformant_server() -> None:
    server = MCPServer("catalog", extensions=[_NonConformantGetSkill()])
    async with Client(server) as client:
        with pytest.raises(ValueError, match="returned skill"):
            await get_skill(client.session, "skill://other/SKILL.md")
