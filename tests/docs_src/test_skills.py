"""`docs/advanced/skills.md`: every claim the page makes, proved against the real SDK."""

from pathlib import Path

import pytest
from mcp_types import INVALID_PARAMS, TextResourceContents

from docs_src.skills import tutorial001, tutorial002
from mcp import Client
from mcp.client.extensions.skills import Skills
from mcp.shared.exceptions import MCPError

pytestmark = pytest.mark.anyio


async def test_list_skills_returns_the_registered_skill() -> None:
    """tutorial001: `list_skills` returns the one skill the server declared."""
    skills = Skills()
    async with Client(tutorial001.mcp, extensions=[skills]) as client:
        result = await client.extension(Skills).list_skills()
    assert [s.uri for s in result] == [tutorial001.SKILL_URI]


async def test_get_skill_answers_by_uri() -> None:
    """tutorial001: `get_skill` returns the same entry `list_skills` does."""
    skills = Skills()
    async with Client(tutorial001.mcp, extensions=[skills]) as client:
        skill = await client.extension(Skills).get_skill(tutorial001.SKILL_URI)
    assert skill.frontmatter["name"] == "git-workflow"


async def test_get_skill_rejects_an_unknown_uri() -> None:
    """tutorial001: `get_skill` raises `-32602` (Invalid params) for an unknown skill."""
    skills = Skills()
    async with Client(tutorial001.mcp, extensions=[skills]) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.extension(Skills).get_skill("skill://unknown/SKILL.md")
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


async def test_a_directory_of_skills_is_served_with_no_handlers() -> None:
    """tutorial002: `SkillCatalog` over `FilesystemSkillProvider` lists the sample skill and its files."""
    server = await tutorial002.build_server(Path(tutorial002.__file__).parent / "skills")
    skills = Skills()
    async with Client(server, extensions=[skills]) as client:
        skill = (await client.extension(Skills).list_skills())[0]
        children = await client.extension(Skills).read_directory("skill://git-workflow/references")
        contents = (await client.read_resource("skill://git-workflow/references/conventions.md")).contents[0]

    assert skill.uri == "skill://git-workflow/SKILL.md"
    assert skill.frontmatter["name"] == "git-workflow"
    assert isinstance(skill.resources, list)
    assert [r.uri for r in skill.resources] == [
        "skill://git-workflow/SKILL.md",
        "skill://git-workflow/references/conventions.md",
    ]
    assert [r.uri for r in children] == ["skill://git-workflow/references/conventions.md"]
    assert isinstance(contents, TextResourceContents)
    assert contents.text.startswith("# Conventions")
