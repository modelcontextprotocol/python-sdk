# Concepts

!!! warning "Under Construction"

    This page is currently being written. Check back soon for complete documentation.

<!--
  - Server vs Client
  - Three primitives (tools, resources, prompts)
  - Transports (stdio, SSE, streamable HTTP)
  - Context and sessions
  - Lifecycle and state
 -->

## Server Instructions

When a server initializes, it can send instructions tot he client explaining how the tools can be used as a collective group, this can be thought of like an instructions manual for the consumer of a given server.

### Basic Usage

Here's how you add instructions to your server:

```python title="server.py"
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="Weather & Calendar",
    instructions="""
# How to use this server

## Weather Tools
- get_weather: Current conditions
- get_forecast: Future predictions

## Calendar Tools
- list_events: View your calendar
- create_event: Schedule something

tip: Check the weather forecast before scheduling outdoor events
"""  
)

@mcp.tool()
def get_weather(location: str) -> dict:
    """Get current weather"""
    return {"temp": 72, "condition": "sunny"}

@mcp.tool()
def create_event(title: str, date: str) -> dict:
    """Schedule an event"""
    return {"id": "evt_123", "title": title, "date": date}
```

1. Instructions support Markdown formatting for better readability.

!!! info
    The `instructions` field is part of the `InitializeResult` that clients receive during the connection handshake. It's optional, but super helpful when you have multiple related tools.

### When to Use Instructions

Instructions are shown to both humans (in client UIs like MCP Inspector) and LLMs (as context for tool selection). They work best when you have multiple related tools and need to explain how they work together.

Use instructions when:

- Your server has tools from different domains (like weather + calendar)
- Tools should be used in a specific order or sequence
- You need to share constraints or best practices

They're **not** for documenting individual tool parameters - use docstrings for that.

### Writing Good Instructions

Focus on tool relationships and workflows, not individual tool details:

```python title="good_instructions.py"
instructions = """
## File Operations
- read_file: Load file contents
- write_file: Save to disk

Always use read_file before write_file to avoid overwriting data.

## Rate Limits
- API calls: 100/hour
- File operations: No limit
"""
```

Keep them concise (10-30 lines) and use Markdown headers to group related tools.

!!! info
    Access instructions from tools using `ctx.fastmcp.instructions` to expose them programmatically.

### Low-Level Server

If you're using the low-level server API, you set instructions the same way:

```python
from mcp.server.lowlevel import Server

server = Server(
    name="My Server",
    instructions="Your usage guide here..."
)
```

### Complete Example

For a full working example showing instructions with a multi-domain server, check out [examples/snippets/servers/server_instructions.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/server_instructions.py).
