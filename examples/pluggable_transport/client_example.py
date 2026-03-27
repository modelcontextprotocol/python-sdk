"""Example demonstrating how the high-level `Client` class interacts with
the `BaseClientSession` abstraction for callbacks.
"""

import asyncio

from mcp import Client
from mcp.client.base_client_session import BaseClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared._context import RequestContext
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    TextContent,
)


async def main():
    # 1. Create a simple server with a tool that requires sampling
    server = MCPServer("ExampleServer")

    @server.tool("ask_assistant")
    async def ask_assistant(message: str) -> str:
        # The tool asks the client to sample a message (requires the sampling callback)
        print(f"[Server] Received request: {message}")
        result = await server.get_context().session.create_message(
            messages=[{"role": "user", "content": {"type": "text", "text": message}}],
            max_tokens=100,
        )
        return f"Assistant replied: {result.content.text}"

    # 2. Define a callback typed against the abstract `BaseClientSession`.
    # Notice that we are NOT tied to `ClientSession` streams here!
    # Because of the contravariance assigned to `ClientSessionT_contra` in the
    # Protocol, this callback is a completely valid mathematical subtype of the
    # `SamplingFnT[ClientSession]` expected by `Client` during instantiation.
    async def abstract_sampling_callback(
        context: RequestContext[BaseClientSession], params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        print("[Client Callback] Server requested sampling via abstract callback!")

        # We can safely use `BaseClientSession` abstract methods on `context.session`.
        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text="Hello from the abstract callback!"),
            model="gpt-test",
            stop_reason="endTurn",
        )

    # 3. Instantiate the Client, injecting our abstract callback.
    # The SDK automatically handles the underlying streams and creates the concrete
    # `ClientSession`, which safely fulfills the `BaseClientSession` contract our
    # callback expects.
    async with Client(server, sampling_callback=abstract_sampling_callback) as client:
        print("Executing tool 'ask_assistant' from the Client...")
        result = await client.call_tool("ask_assistant", {"message": "Please say hello"})

        if not result.is_error:
            for content in result.content:
                if isinstance(content, TextContent):
                    print(f"Server Tool Output: {content.text}")


if __name__ == "__main__":
    asyncio.run(main())
