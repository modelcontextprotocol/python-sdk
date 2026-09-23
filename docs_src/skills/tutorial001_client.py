import anyio

from mcp import Client
from mcp.client.skills import Skills, verify_skill_resource
from mcp.types import TextResourceContents


async def main() -> None:
    skills = Skills()
    async with Client("http://localhost:8000/mcp", extensions=[skills]) as client:
        catalog = skills.bind(client)
        for skill in await catalog.list_skills():
            print(skill.uri, skill.frontmatter["description"])

        skill = await catalog.get_skill("skill://git-workflow/SKILL.md")
        result = await catalog.read_skill_uri(skill.uri)
        content = result.contents[0]
        if isinstance(content, TextResourceContents):
            verify_skill_resource(skill, skill.uri, content.text.encode())
            print(content.text)


if __name__ == "__main__":
    anyio.run(main)
