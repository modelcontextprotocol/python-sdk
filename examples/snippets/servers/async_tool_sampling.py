"""
Async tool with sampling (LLM interaction) example.

cd to the `examples/snippets/clients` directory and run:
    uv run server async_tool_sampling stdio
"""

import asyncio

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import SamplingMessage, TextContent

mcp = FastMCP("Async Tool Sampling")


@mcp.tool(invocation_modes=["async"])
async def generate_content(topic: str, content_type: str, ctx: Context) -> str:  # type: ignore[type-arg]
    """Generate content using LLM sampling with progress updates."""
    await ctx.info(f"Starting {content_type} generation for topic: {topic}")

    # Simulate preparation
    await asyncio.sleep(0.5)
    await ctx.report_progress(0.2, 1.0, "Preparing content generation")

    # Create prompt based on content type
    prompts = {
        "poem": f"Write a creative poem about {topic}",
        "story": f"Write a short story about {topic}",
        "summary": f"Write a concise summary about {topic}",
        "analysis": f"Provide a detailed analysis of {topic}",
    }

    prompt = prompts.get(content_type, f"Write about {topic}")
    await ctx.report_progress(0.4, 1.0, "Prompt prepared")

    # Use LLM sampling
    await ctx.info("Requesting content from LLM...")
    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=prompt),
            )
        ],
        max_tokens=200,
    )

    await ctx.report_progress(0.8, 1.0, "Content generated")

    # Process the result
    await asyncio.sleep(0.3)
    await ctx.report_progress(1.0, 1.0, "Processing complete")

    if result.content.type == "text":
        await ctx.info(f"Successfully generated {content_type}")
        return f"Generated {content_type} about '{topic}':\n\n{result.content.text}"
    else:
        await ctx.warning("Unexpected content type from LLM")
        return f"Generated {content_type} about '{topic}': {str(result.content)}"


@mcp.tool(invocation_modes=["async"])
async def multi_step_generation(topic: str, steps: list[str], ctx: Context) -> dict[str, str]:  # type: ignore[type-arg]
    """Generate multiple pieces of content in sequence."""
    await ctx.info(f"Starting multi-step generation for: {topic}")

    results: dict[str, str] = {}
    total_steps = len(steps)

    for i, step in enumerate(steps):
        await ctx.debug(f"Processing step {i + 1}: {step}")

        # Create step-specific prompt
        prompt = f"For the topic '{topic}', please {step}"

        # Use LLM sampling for this step
        result = await ctx.session.create_message(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(type="text", text=prompt),
                )
            ],
            max_tokens=150,
        )

        # Store result
        if result.content.type == "text":
            results[step] = result.content.text
        else:
            results[step] = str(result.content)

        # Report progress
        progress = (i + 1) / total_steps
        await ctx.report_progress(progress, 1.0, f"Completed step {i + 1}/{total_steps}: {step}")

        # Small delay between steps
        await asyncio.sleep(0.2)

    await ctx.info(f"Multi-step generation complete! Generated {len(results)} pieces of content")
    return results


if __name__ == "__main__":
    mcp.run()
