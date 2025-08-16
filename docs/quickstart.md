# Quickstart

Get started with the MCP Python SDK in minutes by building a simple server that exposes tools, resources, and prompts.

## Prerequisites

- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/) package manager

## Create your first MCP server

### 1. Set up your project

Create a new project and add the MCP SDK:

```bash
uv init my-mcp-server
cd my-mcp-server
uv add "mcp[cli]"
```

### 2. Create a simple server

Create a file called `server.py`:

```python
"""
Simple MCP server with tools, resources, and prompts.

Run with: uv run mcp dev server.py
"""

from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("Demo Server")


# Add a tool for mathematical operations
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@mcp.tool()
def multiply(a: int, b: int) -> int:
    """Multiply two numbers together."""
    return a * b


# Add a dynamic resource for greetings
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting for someone."""
    return f"Hello, {name}! Welcome to our MCP server."


@mcp.resource("info://server")
def get_server_info() -> str:
    """Get information about this server."""
    return """This is a demo MCP server that provides:
    - Mathematical operations (add, multiply)
    - Personalized greetings
    - Server information
    """


# Add a prompt template
@mcp.prompt()
def greet_user(name: str, style: str = "friendly") -> str:
    """Generate a greeting prompt for a user."""
    styles = {
        "friendly": "Please write a warm, friendly greeting",
        "formal": "Please write a formal, professional greeting",
        "casual": "Please write a casual, relaxed greeting",
    }

    style_instruction = styles.get(style, styles["friendly"])
    return f"{style_instruction} for someone named {name}."


if __name__ == "__main__":
    # Run the server
    mcp.run()
```

### 3. Test your server

Test the server using the MCP Inspector:

```bash
uv run mcp dev server.py
```

After installing any required dependencies, your default web browser should open the MCP Inspector where you can:

- Call tools (`add` and `multiply`)
- Read resources (`greeting://YourName` and `info://server`)
- Use prompts (`greet_user`)

### 4. Install in Claude Desktop

Once you're happy with your server, install it in Claude Desktop:

```bash
uv run mcp install server.py
```

Claude Desktop will now have access to your tools and resources!

## What you've built

Your server now provides:

### Tools
- **add(a, b)** - Adds two numbers
- **multiply(a, b)** - Multiplies two numbers

### Resources
- **greeting://{name}** - Personalized greetings (e.g., `greeting://Alice`)
- **info://server** - Server information

### Prompts
- **greet_user** - Generates greeting prompts with different styles

## Try these examples

In the MCP Inspector or Claude Desktop, try:

- Call the `add` tool: `{"a": 5, "b": 3}` → Returns `8`
- Read a greeting: `greeting://World` → Returns `"Hello, World! Welcome to our MCP server."`
- Use the greet_user prompt with `name: "Alice", style: "formal"`

## Next steps

- **[Learn about servers](servers.md)** - Understanding server lifecycle and configuration
- **[Explore tools](tools.md)** - Advanced tool patterns and structured output
- **[Working with resources](resources.md)** - Resource templates and patterns
- **[Running servers](running-servers.md)** - Development and production deployment options