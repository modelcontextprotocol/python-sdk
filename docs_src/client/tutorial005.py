import anyio

from mcp import Client


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        listed = await client.list_prompts()
        print(listed.prompts)

        result = await client.get_prompt("recommend", {"genre": "poetry"})
        for message in result.messages:
            print(message.role, message.content)


if __name__ == "__main__":
    anyio.run(main)
