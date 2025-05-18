# MCP Simple Prompt

A simple MCP server that exposes a customizable prompt template with optional context and topic parameters.

## Usage

Start the server using either stdio (default) or SSE transport:

```bash
# Using stdio transport (default)
uv run mcp-simple-prompt

# Using SSE transport on custom port
uv run mcp-simple-prompt --transport sse --port 8000
```

The server exposes a prompt named "simple" that accepts two optional arguments:

- `context`: Additional context to consider
- `topic`: Specific topic to focus on

## Example

Using the MCP client, you can retrieve the prompt like this using the STDIO transport:

```python
import asyncio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main():
    async with stdio_client(
        StdioServerParameters(command="uv", args=["run", "mcp-simple-prompt"])
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available prompts
            prompts = await session.list_prompts()
            print(prompts)

            # Get the prompt with arguments
            prompt = await session.get_prompt(
                "simple",
                {
                    "context": "User is a software developer",
                    "topic": "Python async programming",
                },
            )
            print(prompt)


asyncio.run(main())
```
