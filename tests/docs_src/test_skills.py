"""`docs/advanced/skills.md`: every claim the page makes, proved against the real SDK."""

import pytest
from mcp_types import INVALID_PARAMS, TextResourceContents

from docs_src.skills import tutorial001
from mcp import Client
from mcp.client.skills import Skills, verify_skill_resource
from mcp.shared.exceptions import MCPError

pytestmark = pytest.mark.anyio


async def test_list_skills_returns_the_registered_skill() -> None:
    """tutorial001: `list_skills` returns the one skill the server declared."""
    skills = Skills()
    async with Client(tutorial001.mcp, extensions=[skills]) as client:
        result = await skills.bind(client).list_skills()
    assert [s.uri for s in result] == [tutorial001.SKILL_URI]


async def test_get_skill_answers_by_uri() -> None:
    """tutorial001: `get_skill` returns the same entry `list_skills` does."""
    skills = Skills()
    async with Client(tutorial001.mcp, extensions=[skills]) as client:
        skill = await skills.bind(client).get_skill(tutorial001.SKILL_URI)
    assert skill.frontmatter["name"] == "git-workflow"


async def test_get_skill_rejects_an_unknown_uri() -> None:
    """tutorial001: `get_skill` raises `-32602` (Invalid params) for an unknown skill."""
    skills = Skills()
    async with Client(tutorial001.mcp, extensions=[skills]) as client:
        with pytest.raises(MCPError) as exc_info:
            await skills.bind(client).get_skill("skill://unknown/SKILL.md")
    assert exc_info.value.code == INVALID_PARAMS


async def test_the_skill_file_is_served_as_an_ordinary_resource() -> None:
    """tutorial001: `Skills` never reads or serves content itself — the file is registered
    through `mcp.add_resource`, the SDK's ordinary resource machinery."""
    async with Client(tutorial001.mcp) as client:
        result = await client.read_resource(tutorial001.SKILL_URI)
    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    assert contents.mime_type == "text/markdown"
    assert contents.text == tutorial001.SKILL_MD


async def test_read_skill_uri_content_verifies_against_the_held_skill() -> None:
    """tutorial001_client: fetch the entry, read the file, verify the bytes against it -
    the digest/size check `verify_skill_resource` performs."""
    skills = Skills()
    async with Client(tutorial001.mcp, extensions=[skills]) as client:
        catalog = skills.bind(client)
        skill = await catalog.get_skill(tutorial001.SKILL_URI)
        result = await catalog.read_skill_uri(skill.uri)
    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    verify_skill_resource(skill, skill.uri, contents.text.encode())
