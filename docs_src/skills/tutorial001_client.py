import anyio
from mcp_types import TextResourceContents

from mcp import Client
from mcp.client.skills import get_skill, list_skills, read_skill_uri, verify_skill_resource


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        for skill in await list_skills(client.session):
            print(skill.uri, skill.frontmatter["description"])

        skill = await get_skill(client.session, "skill://git-workflow/SKILL.md")
        result = await read_skill_uri(client.session, skill.uri)
        content = result.contents[0]
        if isinstance(content, TextResourceContents):
            verify_skill_resource(skill, skill.uri, content.text.encode())
            print(content.text)


if __name__ == "__main__":
    anyio.run(main)
