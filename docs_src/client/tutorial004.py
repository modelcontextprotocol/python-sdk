import anyio

from mcp import Client
from mcp.types import TextResourceContents


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        listed = await client.list_resources()
        print([resource.uri for resource in listed.resources])

        templates = await client.list_resource_templates()
        print([template.uri_template for template in templates.resource_templates])

        result = await client.read_resource("catalog://genres/poetry")
        for contents in result.contents:
            if isinstance(contents, TextResourceContents):
                print(contents.text)


if __name__ == "__main__":
    anyio.run(main)
