"""cd to the `examples/snippets` directory and run:
uv run completion-client
"""

import asyncio
import os

from mcp_types import PromptReference, ResourceTemplateReference

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
    command="uv",
    args=["run", "server", "completion", "stdio"],
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


async def run():
    """Run the completion client example."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            templates = await session.list_resource_templates()
            print("Available resource templates:")
            for template in templates.resource_templates:
                print(f"  - {template.uri_template}")

            prompts = await session.list_prompts()
            print("\nAvailable prompts:")
            for prompt in prompts.prompts:
                print(f"  - {prompt.name}")

            if templates.resource_templates:
                template = templates.resource_templates[0]
                print(f"\nCompleting arguments for resource template: {template.uri_template}")

                # Complete without context
                result = await session.complete(
                    ref=ResourceTemplateReference(type="ref/resource", uri=template.uri_template),
                    argument={"name": "owner", "value": "model"},
                )
                print(f"Completions for 'owner' starting with 'model': {result.completion.values}")

                # Complete with context - repo suggestions based on owner
                result = await session.complete(
                    ref=ResourceTemplateReference(type="ref/resource", uri=template.uri_template),
                    argument={"name": "repo", "value": ""},
                    context_arguments={"owner": "modelcontextprotocol"},
                )
                print(f"Completions for 'repo' with owner='modelcontextprotocol': {result.completion.values}")

            if prompts.prompts:
                prompt_name = prompts.prompts[0].name
                print(f"\nCompleting arguments for prompt: {prompt_name}")

                result = await session.complete(
                    ref=PromptReference(type="ref/prompt", name=prompt_name),
                    argument={"name": "style", "value": ""},
                )
                print(f"Completions for 'style' argument: {result.completion.values}")


def main():
    """Entry point for the completion client."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
