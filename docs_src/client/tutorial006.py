import anyio

from mcp import Client
from mcp.types import PromptReference


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        result = await client.complete(
            ref=PromptReference(type="ref/prompt", name="recommend"),
            argument={"name": "genre", "value": "p"},
        )
        print(result.completion.values)


if __name__ == "__main__":
    anyio.run(main)
