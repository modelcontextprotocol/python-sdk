import anyio

from mcp import Client
from mcp.client.skills import Skills
from mcp.types import TextResourceContents


async def main() -> None:
    async with Client("http://localhost:8000/mcp", extensions=[Skills()]) as client:
        catalog = client.extension(Skills)
        for skill in await catalog.list_skills():
            print(skill.uri, skill.frontmatter["description"])

        skill = await catalog.get_skill("skill://git-workflow/SKILL.md")
        result = await catalog.read_skill_resource(skill)
        content = result.contents[0]
        if isinstance(content, TextResourceContents):
            print(content.text)


if __name__ == "__main__":
    anyio.run(main)
