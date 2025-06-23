#!/usr/bin/env python3
"""
Example low-level MCP server demonstrating structured output support.

This example shows how to use the low-level server API to return both
human-readable content and machine-readable structured data from tools,
with automatic validation against output schemas.

The low-level API provides direct control over request handling and
allows tools to return different types of responses:
1. Content only (list of content blocks)
2. Structured data only (dict that gets serialized to JSON)
3. Both content and structured data (tuple)
"""

import asyncio
from datetime import datetime
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# Create low-level server instance
server = Server("structured-output-lowlevel-example")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """List available tools with their schemas."""
    return [
        types.Tool(
            name="analyze_text",
            description="Analyze text and return structured insights",
            inputSchema={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to analyze"}},
                "required": ["text"],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "word_count": {"type": "integer"},
                    "char_count": {"type": "integer"},
                    "sentence_count": {"type": "integer"},
                    "most_common_words": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"word": {"type": "string"}, "count": {"type": "integer"}},
                            "required": ["word", "count"],
                        },
                    },
                },
                "required": ["word_count", "char_count", "sentence_count", "most_common_words"],
            },
        ),
        types.Tool(
            name="get_weather",
            description="Get weather information (simulated)",
            inputSchema={
                "type": "object",
                "properties": {"city": {"type": "string", "description": "City name"}},
                "required": ["city"],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "temperature": {"type": "number"},
                    "conditions": {"type": "string"},
                    "humidity": {"type": "integer", "minimum": 0, "maximum": 100},
                    "wind_speed": {"type": "number"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
                "required": ["temperature", "conditions", "humidity", "wind_speed", "timestamp"],
            },
        ),
        types.Tool(
            name="calculate_statistics",
            description="Calculate statistics for a list of numbers",
            inputSchema={
                "type": "object",
                "properties": {
                    "numbers": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "List of numbers to analyze",
                    }
                },
                "required": ["numbers"],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "mean": {"type": "number"},
                    "median": {"type": "number"},
                    "min": {"type": "number"},
                    "max": {"type": "number"},
                    "sum": {"type": "number"},
                    "count": {"type": "integer"},
                },
                "required": ["mean", "median", "min", "max", "sum", "count"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """
    Handle tool calls with structured output.

    This low-level handler demonstrates the three ways to return data:
    1. Return a list of content blocks (traditional approach)
    2. Return a dict (gets serialized to JSON and included as structuredContent)
    3. Return a tuple of (content, structured_data) for both
    """

    if name == "analyze_text":
        text = arguments["text"]

        # Analyze the text
        words = text.split()
        word_count = len(words)
        char_count = len(text)
        sentences = text.replace("?", ".").replace("!", ".").split(".")
        sentence_count = len([s for s in sentences if s.strip()])

        # Count word frequencies
        word_freq = {}
        for word in words:
            word_lower = word.lower().strip('.,!?;:"')
            if word_lower:
                word_freq[word_lower] = word_freq.get(word_lower, 0) + 1

        # Get top 5 most common words
        most_common = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:5]
        most_common_words = [{"word": word, "count": count} for word, count in most_common]

        # Example 3: Return both content and structured data
        # The low-level server will validate the structured data against outputSchema
        content = [
            types.TextContent(
                type="text",
                text=f"Text analysis complete:\n"
                f"- {word_count} words\n"
                f"- {char_count} characters\n"
                f"- {sentence_count} sentences\n"
                f"- Most common words: {', '.join(w['word'] for w in most_common_words)}",
            )
        ]

        structured = {
            "word_count": word_count,
            "char_count": char_count,
            "sentence_count": sentence_count,
            "most_common_words": most_common_words,
        }

        return (content, structured)

    elif name == "get_weather":
        # city = arguments["city"]  # Would be used with real weather API

        # Simulate weather data (in production, call a real weather API)
        import random

        weather_conditions = ["sunny", "cloudy", "rainy", "partly cloudy", "foggy"]

        weather_data = {
            "temperature": round(random.uniform(0, 35), 1),
            "conditions": random.choice(weather_conditions),
            "humidity": random.randint(30, 90),
            "wind_speed": round(random.uniform(0, 30), 1),
            "timestamp": datetime.now().isoformat(),
        }

        # Example 2: Return structured data only
        # The low-level server will serialize this to JSON content automatically
        return weather_data

    elif name == "calculate_statistics":
        numbers = arguments["numbers"]

        if not numbers:
            raise ValueError("Cannot calculate statistics for empty list")

        sorted_nums = sorted(numbers)
        count = len(numbers)

        # Calculate statistics
        mean = sum(numbers) / count

        if count % 2 == 0:
            median = (sorted_nums[count // 2 - 1] + sorted_nums[count // 2]) / 2
        else:
            median = sorted_nums[count // 2]

        stats = {
            "mean": mean,
            "median": median,
            "min": sorted_nums[0],
            "max": sorted_nums[-1],
            "sum": sum(numbers),
            "count": count,
        }

        # Example 3: Return both content and structured data
        content = [
            types.TextContent(
                type="text",
                text=f"Statistics for {count} numbers:\n"
                f"Mean: {stats['mean']:.2f}, Median: {stats['median']:.2f}\n"
                f"Range: {stats['min']} to {stats['max']}\n"
                f"Sum: {stats['sum']}",
            )
        ]

        return (content, stats)

    else:
        raise ValueError(f"Unknown tool: {name}")


async def run():
    """Run the low-level server using stdio transport."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="structured-output-lowlevel-example",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(run())
