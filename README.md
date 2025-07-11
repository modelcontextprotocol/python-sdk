# MCP Python SDK

<div align="center">

<strong>Python implementation of the Model Context Protocol (MCP)</strong>

[![PyPI][pypi-badge]][pypi-url]
[![MIT licensed][mit-badge]][mit-url]
[![Python Version][python-badge]][python-url]
[![Documentation][docs-badge]][docs-url]
[![Specification][spec-badge]][spec-url]
[![GitHub Discussions][discussions-badge]][discussions-url]

</div>

<!-- omit in toc -->
## Table of Contents

- [MCP Python SDK](#mcp-python-sdk)
  - [Overview](#overview)
  - [Installation](#installation)
    - [Adding MCP to your python project](#adding-mcp-to-your-python-project)
    - [Running the standalone MCP development tools](#running-the-standalone-mcp-development-tools)
  - [Quickstart](#quickstart)
  - [What is MCP?](#what-is-mcp)
  - [Core Concepts](#core-concepts)
    - [Server](#server)
    - [Resources](#resources)
    - [Tools](#tools)
      - [Structured Output](#structured-output)
    - [Prompts](#prompts)
    - [Images](#images)
    - [Context](#context)
    - [Completions](#completions)
    - [Elicitation](#elicitation)
    - [Sampling](#sampling)
    - [Logging and Notifications](#logging-and-notifications)
    - [Authentication](#authentication)
  - [Running Your Server](#running-your-server)
    - [Development Mode](#development-mode)
    - [Claude Desktop Integration](#claude-desktop-integration)
    - [Direct Execution](#direct-execution)
    - [Mounting to an Existing ASGI Server](#mounting-to-an-existing-asgi-server)
  - [Examples](#examples)
    - [Echo Server](#echo-server)
    - [SQLite Explorer](#sqlite-explorer)
  - [Advanced Usage](#advanced-usage)
    - [Low-Level Server](#low-level-server)
    - [Writing MCP Clients](#writing-mcp-clients)
    - [MCP Primitives](#mcp-primitives)
    - [Server Capabilities](#server-capabilities)
  - [Documentation](#documentation)
  - [Contributing](#contributing)
  - [License](#license)

[pypi-badge]: https://img.shields.io/pypi/v/mcp.svg
[pypi-url]: https://pypi.org/project/mcp/
[mit-badge]: https://img.shields.io/pypi/l/mcp.svg
[mit-url]: https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE
[python-badge]: https://img.shields.io/pypi/pyversions/mcp.svg
[python-url]: https://www.python.org/downloads/
[docs-badge]: https://img.shields.io/badge/docs-modelcontextprotocol.io-blue.svg
[docs-url]: https://modelcontextprotocol.io
[spec-badge]: https://img.shields.io/badge/spec-spec.modelcontextprotocol.io-blue.svg
[spec-url]: https://spec.modelcontextprotocol.io
[discussions-badge]: https://img.shields.io/github/discussions/modelcontextprotocol/python-sdk
[discussions-url]: https://github.com/modelcontextprotocol/python-sdk/discussions

## Overview

The Model Context Protocol allows applications to provide context for LLMs in a standardized way, separating the concerns of providing context from the actual LLM interaction. This Python SDK implements the full MCP specification, making it easy to:

- Build MCP clients that can connect to any MCP server
- Create MCP servers that expose resources, prompts and tools
- Use standard transports like stdio, SSE, and Streamable HTTP
- Handle all MCP protocol messages and lifecycle events

## Installation

### Adding MCP to your python project

We recommend using [uv](https://docs.astral.sh/uv/) to manage your Python projects.

If you haven't created a uv-managed project yet, create one:

   ```bash
   uv init mcp-server-demo
   cd mcp-server-demo
   ```

   Then add MCP to your project dependencies:

   ```bash
   uv add "mcp[cli]"
   ```

Alternatively, for projects using pip for dependencies:

```bash
pip install "mcp[cli]"
```

### Running the standalone MCP development tools

To run the mcp command with uv:

```bash
uv run mcp
```

## Quickstart

Let's create a simple MCP server that exposes a calculator tool and some data:

```python
# server.py
from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("Demo")


# Add an addition tool
@mcp.tool()
def sum(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"
```

You can install this server in [Claude Desktop](https://claude.ai/download) and interact with it right away by running:

```bash
uv run mcp install server.py
```

Alternatively, you can test it with the MCP Inspector:

```bash
uv run mcp dev server.py
```

## What is MCP?

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io) lets you build servers that expose data and functionality to LLM applications in a secure, standardized way. Think of it like a web API, but specifically designed for LLM interactions. MCP servers can:

- Expose data through **Resources** (think of these sort of like GET endpoints; they are used to load information into the LLM's context)
- Provide functionality through **Tools** (sort of like POST endpoints; they are used to execute code or otherwise produce a side effect)
- Define interaction patterns through **Prompts** (reusable templates for LLM interactions)
- And more!

## Core Concepts

### Server

The FastMCP server is your core interface to the MCP protocol. It handles connection management, protocol compliance, and message routing:

```python
# Add lifespan support for startup/shutdown with strong typing
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fake_database import Database  # Replace with your actual DB type

from mcp.server.fastmcp import FastMCP

# Create a named server
mcp = FastMCP("My App")

# Specify dependencies for deployment and development
mcp = FastMCP("My App", dependencies=["pandas", "numpy"])


@dataclass
class AppContext:
    db: Database


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle with type-safe context"""
    # Initialize on startup
    db = await Database.connect()
    try:
        yield AppContext(db=db)
    finally:
        # Cleanup on shutdown
        await db.disconnect()


# Pass lifespan to server
mcp = FastMCP("My App", lifespan=app_lifespan)


# Access type-safe lifespan context in tools
@mcp.tool()
def query_db() -> str:
    """Tool that uses initialized resources"""
    ctx = mcp.get_context()
    db = ctx.request_context.lifespan_context.db
    return db.query()
```

### Resources

Resources are how you expose data to LLMs. They're similar to GET endpoints in a REST API - they provide data but shouldn't perform significant computation or have side effects:

<!-- snippet-source examples/snippets/servers/basic_resource.py -->
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="Resource Example")


@mcp.resource("file://documents/{name}")
def read_document(name: str) -> str:
    """Read a document by name."""
    # This would normally read from disk
    return f"Content of {name}"


@mcp.resource("config://settings")
def get_settings() -> str:
    """Get application settings."""
    return """{
  "theme": "dark",
  "language": "en",
  "debug": false
}"""
```

_Full example: [examples/snippets/servers/basic_resource.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/basic_resource.py)_
<!-- /snippet-source -->

### Tools

Tools let LLMs take actions through your server. Unlike resources, tools are expected to perform computation and have side effects:

<!-- snippet-source examples/snippets/servers/basic_tool.py -->
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="Tool Example")


@mcp.tool()
def sum(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@mcp.tool()
def get_weather(city: str, unit: str = "celsius") -> str:
    """Get weather for a city."""
    # This would normally call a weather API
    return f"Weather in {city}: 22degrees{unit[0].upper()}"
```

_Full example: [examples/snippets/servers/basic_tool.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/basic_tool.py)_
<!-- /snippet-source -->

#### Structured Output

Tools will return structured results by default, if their return type
annotation is compatible. Otherwise, they will return unstructured results.

Structured output supports these return types:

- Pydantic models (BaseModel subclasses)
- TypedDicts
- Dataclasses and other classes with type hints
- `dict[str, T]` (where T is any JSON-serializable type)
- Primitive types (str, int, float, bool, bytes, None) - wrapped in `{"result": value}`
- Generic types (list, tuple, Union, Optional, etc.) - wrapped in `{"result": value}`

Classes without type hints cannot be serialized for structured output. Only
classes with properly annotated attributes will be converted to Pydantic models
for schema generation and validation.

Structured results are automatically validated against the output schema
generated from the annotation. This ensures the tool returns well-typed,
validated data that clients can easily process.

**Note:** For backward compatibility, unstructured results are also
returned. Unstructured results are provided for backward compatibility
with previous versions of the MCP specification, and are quirks-compatible
with previous versions of FastMCP in the current version of the SDK.

**Note:** In cases where a tool function's return type annotation
causes the tool to be classified as structured _and this is undesirable_,
the  classification can be suppressed by passing `structured_output=False`
to the `@tool` decorator.

```python
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import TypedDict

mcp = FastMCP("Weather Service")


# Using Pydantic models for rich structured data
class WeatherData(BaseModel):
    temperature: float = Field(description="Temperature in Celsius")
    humidity: float = Field(description="Humidity percentage")
    condition: str
    wind_speed: float


@mcp.tool()
def get_weather(city: str) -> WeatherData:
    """Get structured weather data"""
    return WeatherData(
        temperature=22.5, humidity=65.0, condition="partly cloudy", wind_speed=12.3
    )


# Using TypedDict for simpler structures
class LocationInfo(TypedDict):
    latitude: float
    longitude: float
    name: str


@mcp.tool()
def get_location(address: str) -> LocationInfo:
    """Get location coordinates"""
    return LocationInfo(latitude=51.5074, longitude=-0.1278, name="London, UK")


# Using dict[str, Any] for flexible schemas
@mcp.tool()
def get_statistics(data_type: str) -> dict[str, float]:
    """Get various statistics"""
    return {"mean": 42.5, "median": 40.0, "std_dev": 5.2}


# Ordinary classes with type hints work for structured output
class UserProfile:
    name: str
    age: int
    email: str | None = None

    def __init__(self, name: str, age: int, email: str | None = None):
        self.name = name
        self.age = age
        self.email = email


@mcp.tool()
def get_user(user_id: str) -> UserProfile:
    """Get user profile - returns structured data"""
    return UserProfile(name="Alice", age=30, email="alice@example.com")


# Classes WITHOUT type hints cannot be used for structured output
class UntypedConfig:
    def __init__(self, setting1, setting2):
        self.setting1 = setting1
        self.setting2 = setting2


@mcp.tool()
def get_config() -> UntypedConfig:
    """This returns unstructured output - no schema generated"""
    return UntypedConfig("value1", "value2")


# Lists and other types are wrapped automatically
@mcp.tool()
def list_cities() -> list[str]:
    """Get a list of cities"""
    return ["London", "Paris", "Tokyo"]
    # Returns: {"result": ["London", "Paris", "Tokyo"]}


@mcp.tool()
def get_temperature(city: str) -> float:
    """Get temperature as a simple float"""
    return 22.5
    # Returns: {"result": 22.5}
```

### Prompts

Prompts are reusable templates that help LLMs interact with your server effectively:

<!-- snippet-source examples/snippets/servers/basic_prompt.py -->
```python
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base

mcp = FastMCP(name="Prompt Example")


@mcp.prompt(title="Code Review")
def review_code(code: str) -> str:
    return f"Please review this code:\n\n{code}"


@mcp.prompt(title="Debug Assistant")
def debug_error(error: str) -> list[base.Message]:
    return [
        base.UserMessage("I'm seeing this error:"),
        base.UserMessage(error),
        base.AssistantMessage("I'll help debug that. What have you tried so far?"),
    ]
```

_Full example: [examples/snippets/servers/basic_prompt.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/basic_prompt.py)_
<!-- /snippet-source -->

### Images

FastMCP provides an `Image` class that automatically handles image data:

```python
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage

mcp = FastMCP("My App")


@mcp.tool()
def create_thumbnail(image_path: str) -> Image:
    """Create a thumbnail from an image"""
    img = PILImage.open(image_path)
    img.thumbnail((100, 100))
    return Image(data=img.tobytes(), format="png")
```

### Context

The Context object gives your tools and resources access to MCP capabilities:

<!-- snippet-source examples/snippets/servers/tool_progress.py -->
```python
from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP(name="Progress Example")


@mcp.tool()
async def long_running_task(task_name: str, ctx: Context, steps: int = 5) -> str:
    """Execute a task with progress updates."""
    await ctx.info(f"Starting: {task_name}")

    for i in range(steps):
        progress = (i + 1) / steps
        await ctx.report_progress(
            progress=progress,
            total=1.0,
            message=f"Step {i + 1}/{steps}",
        )
        await ctx.debug(f"Completed step {i + 1}")

    return f"Task '{task_name}' completed"
```

_Full example: [examples/snippets/servers/tool_progress.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/tool_progress.py)_
<!-- /snippet-source -->

### Completions

MCP supports providing completion suggestions for prompt arguments and resource template parameters. With the context parameter, servers can provide completions based on previously resolved values:

Client usage:

```python
from mcp.client.session import ClientSession
from mcp.types import ResourceTemplateReference


async def use_completion(session: ClientSession):
    # Complete without context
    result = await session.complete(
        ref=ResourceTemplateReference(
            type="ref/resource", uri="github://repos/{owner}/{repo}"
        ),
        argument={"name": "owner", "value": "model"},
    )

    # Complete with context - repo suggestions based on owner
    result = await session.complete(
        ref=ResourceTemplateReference(
            type="ref/resource", uri="github://repos/{owner}/{repo}"
        ),
        argument={"name": "repo", "value": "test"},
        context_arguments={"owner": "modelcontextprotocol"},
    )
```

Server implementation:

<!-- snippet-source examples/snippets/servers/completion.py -->
```python
from mcp.server.fastmcp import FastMCP
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    PromptReference,
    ResourceTemplateReference,
)

mcp = FastMCP(name="Example")


@mcp.resource("github://repos/{owner}/{repo}")
def github_repo(owner: str, repo: str) -> str:
    """GitHub repository resource."""
    return f"Repository: {owner}/{repo}"


@mcp.prompt(description="Code review prompt")
def review_code(language: str, code: str) -> str:
    """Generate a code review."""
    return f"Review this {language} code:\n{code}"


@mcp.completion()
async def handle_completion(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion | None:
    """Provide completions for prompts and resources."""

    # Complete programming languages for the prompt
    if isinstance(ref, PromptReference):
        if ref.name == "review_code" and argument.name == "language":
            languages = ["python", "javascript", "typescript", "go", "rust"]
            return Completion(
                values=[lang for lang in languages if lang.startswith(argument.value)],
                hasMore=False,
            )

    # Complete repository names for GitHub resources
    if isinstance(ref, ResourceTemplateReference):
        if ref.uri == "github://repos/{owner}/{repo}" and argument.name == "repo":
            if context and context.arguments and context.arguments.get("owner") == "modelcontextprotocol":
                repos = ["python-sdk", "typescript-sdk", "specification"]
                return Completion(values=repos, hasMore=False)

    return None
```

_Full example: [examples/snippets/servers/completion.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/completion.py)_
<!-- /snippet-source -->
### Elicitation

Request additional information from users. This example shows an Elicitation during a Tool Call:

<!-- snippet-source examples/snippets/servers/elicitation.py -->
```python
from pydantic import BaseModel, Field

from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP(name="Elicitation Example")


class BookingPreferences(BaseModel):
    """Schema for collecting user preferences."""

    checkAlternative: bool = Field(description="Would you like to check another date?")
    alternativeDate: str = Field(
        default="2024-12-26",
        description="Alternative date (YYYY-MM-DD)",
    )


@mcp.tool()
async def book_table(
    date: str,
    time: str,
    party_size: int,
    ctx: Context,
) -> str:
    """Book a table with date availability check."""
    # Check if date is available
    if date == "2024-12-25":
        # Date unavailable - ask user for alternative
        result = await ctx.elicit(
            message=(f"No tables available for {party_size} on {date}. Would you like to try another date?"),
            schema=BookingPreferences,
        )

        if result.action == "accept" and result.data:
            if result.data.checkAlternative:
                return f"[SUCCESS] Booked for {result.data.alternativeDate}"
            return "[CANCELLED] No booking made"
        return "[CANCELLED] Booking cancelled"

    # Date available
    return f"[SUCCESS] Booked for {date} at {time}"
```

_Full example: [examples/snippets/servers/elicitation.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/elicitation.py)_
<!-- /snippet-source -->

The `elicit()` method returns an `ElicitationResult` with:

- `action`: "accept", "decline", or "cancel"
- `data`: The validated response (only when accepted)
- `validation_error`: Any validation error message

### Sampling

Tools can interact with LLMs through sampling (generating text):

<!-- snippet-source examples/snippets/servers/sampling.py -->
```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import SamplingMessage, TextContent

mcp = FastMCP(name="Sampling Example")


@mcp.tool()
async def generate_poem(topic: str, ctx: Context) -> str:
    """Generate a poem using LLM sampling."""
    prompt = f"Write a short poem about {topic}"

    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=prompt),
            )
        ],
        max_tokens=100,
    )

    if result.content.type == "text":
        return result.content.text
    return str(result.content)
```

_Full example: [examples/snippets/servers/sampling.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/sampling.py)_
<!-- /snippet-source -->

### Logging and Notifications

Tools can send logs and notifications through the context:

<!-- snippet-source examples/snippets/servers/notifications.py -->
```python
from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP(name="Notifications Example")


@mcp.tool()
async def process_data(data: str, ctx: Context) -> str:
    """Process data with logging."""
    # Different log levels
    await ctx.debug(f"Debug: Processing '{data}'")
    await ctx.info("Info: Starting processing")
    await ctx.warning("Warning: This is experimental")
    await ctx.error("Error: (This is just a demo)")

    # Notify about resource changes
    await ctx.session.send_resource_list_changed()

    return f"Processed: {data}"
```

_Full example: [examples/snippets/servers/notifications.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/notifications.py)_
<!-- /snippet-source -->

### Authentication

Authentication can be used by servers that want to expose tools accessing protected resources.

`mcp.server.auth` implements OAuth 2.1 resource server functionality, where MCP servers act as Resource Servers (RS) that validate tokens issued by separate Authorization Servers (AS). This follows the [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization) and implements RFC 9728 (Protected Resource Metadata) for AS discovery.

MCP servers can use authentication by providing an implementation of the `TokenVerifier` protocol:

```python
from mcp import FastMCP
from mcp.server.auth.provider import TokenVerifier, TokenInfo
from mcp.server.auth.settings import AuthSettings


class MyTokenVerifier(TokenVerifier):
    # Implement token validation logic (typically via token introspection)
    async def verify_token(self, token: str) -> TokenInfo:
        # Verify with your authorization server
        ...


mcp = FastMCP(
    "My App",
    token_verifier=MyTokenVerifier(),
    auth=AuthSettings(
        issuer_url="https://auth.example.com",
        resource_server_url="http://localhost:3001",
        required_scopes=["mcp:read", "mcp:write"],
    ),
)
```

For a complete example with separate Authorization Server and Resource Server implementations, see [`examples/servers/simple-auth/`](examples/servers/simple-auth/).

**Architecture:**

- **Authorization Server (AS)**: Handles OAuth flows, user authentication, and token issuance
- **Resource Server (RS)**: Your MCP server that validates tokens and serves protected resources
- **Client**: Discovers AS through RFC 9728, obtains tokens, and uses them with the MCP server

See [TokenVerifier](src/mcp/server/auth/provider.py) for more details on implementing token validation.

## Running Your Server

### Development Mode

The fastest way to test and debug your server is with the MCP Inspector:

```bash
uv run mcp dev server.py

# Add dependencies
uv run mcp dev server.py --with pandas --with numpy

# Mount local code
uv run mcp dev server.py --with-editable .
```

### Claude Desktop Integration

Once your server is ready, install it in Claude Desktop:

```bash
uv run mcp install server.py

# Custom name
uv run mcp install server.py --name "My Analytics Server"

# Environment variables
uv run mcp install server.py -v API_KEY=abc123 -v DB_URL=postgres://...
uv run mcp install server.py -f .env
```

### Direct Execution

For advanced scenarios like custom deployments:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My App")

if __name__ == "__main__":
    mcp.run()
```

Run it with:

```bash
python server.py
# or
uv run mcp run server.py
```

Note that `uv run mcp run` or `uv run mcp dev` only supports server using FastMCP and not the low-level server variant.

### Streamable HTTP Transport

> **Note**: Streamable HTTP transport is superseding SSE transport for production deployments.

```python
from mcp.server.fastmcp import FastMCP

# Stateful server (maintains session state)
mcp = FastMCP("StatefulServer")

# Stateless server (no session persistence)
mcp = FastMCP("StatelessServer", stateless_http=True)

# Stateless server (no session persistence, no sse stream with supported client)
mcp = FastMCP("StatelessServer", stateless_http=True, json_response=True)

# Run server with streamable_http transport
mcp.run(transport="streamable-http")
```

You can mount multiple FastMCP servers in a FastAPI application:

```python
# echo.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="EchoServer", stateless_http=True)


@mcp.tool()
def echo(message: str) -> str:
    """A simple echo tool"""
    return f"Echo: {message}"
```

```python
# math.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="MathServer", stateless_http=True)


@mcp.tool()
def add_two(n: int) -> int:
    """Tool to add two to the input"""
    return n + 2
```

```python
# main.py
import contextlib
from fastapi import FastAPI
from mcp.echo import echo
from mcp.math import math


# Create a combined lifespan to manage both session managers
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(echo.mcp.session_manager.run())
        await stack.enter_async_context(math.mcp.session_manager.run())
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/echo", echo.mcp.streamable_http_app())
app.mount("/math", math.mcp.streamable_http_app())
```

For low level server with Streamable HTTP implementations, see:

- Stateful server: [`examples/servers/simple-streamablehttp/`](examples/servers/simple-streamablehttp/)
- Stateless server: [`examples/servers/simple-streamablehttp-stateless/`](examples/servers/simple-streamablehttp-stateless/)

The streamable HTTP transport supports:

- Stateful and stateless operation modes
- Resumability with event stores
- JSON or SSE response formats
- Better scalability for multi-node deployments

### Mounting to an Existing ASGI Server

> **Note**: SSE transport is being superseded by [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http).

By default, SSE servers are mounted at `/sse` and Streamable HTTP servers are mounted at `/mcp`. You can customize these paths using the methods described below.

You can mount the SSE server to an existing ASGI server using the `sse_app` method. This allows you to integrate the SSE server with other ASGI applications.

```python
from starlette.applications import Starlette
from starlette.routing import Mount, Host
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("My App")

# Mount the SSE server to the existing ASGI server
app = Starlette(
    routes=[
        Mount('/', app=mcp.sse_app()),
    ]
)

# or dynamically mount as host
app.router.routes.append(Host('mcp.acme.corp', app=mcp.sse_app()))
```

When mounting multiple MCP servers under different paths, you can configure the mount path in several ways:

```python
from starlette.applications import Starlette
from starlette.routing import Mount
from mcp.server.fastmcp import FastMCP

# Create multiple MCP servers
github_mcp = FastMCP("GitHub API")
browser_mcp = FastMCP("Browser")
curl_mcp = FastMCP("Curl")
search_mcp = FastMCP("Search")

# Method 1: Configure mount paths via settings (recommended for persistent configuration)
github_mcp.settings.mount_path = "/github"
browser_mcp.settings.mount_path = "/browser"

# Method 2: Pass mount path directly to sse_app (preferred for ad-hoc mounting)
# This approach doesn't modify the server's settings permanently

# Create Starlette app with multiple mounted servers
app = Starlette(
    routes=[
        # Using settings-based configuration
        Mount("/github", app=github_mcp.sse_app()),
        Mount("/browser", app=browser_mcp.sse_app()),
        # Using direct mount path parameter
        Mount("/curl", app=curl_mcp.sse_app("/curl")),
        Mount("/search", app=search_mcp.sse_app("/search")),
    ]
)

# Method 3: For direct execution, you can also pass the mount path to run()
if __name__ == "__main__":
    search_mcp.run(transport="sse", mount_path="/search")
```

For more information on mounting applications in Starlette, see the [Starlette documentation](https://www.starlette.io/routing/#submounting-routes).

## Examples

### Echo Server

A simple server demonstrating resources, tools, and prompts:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Echo")


@mcp.resource("echo://{message}")
def echo_resource(message: str) -> str:
    """Echo a message as a resource"""
    return f"Resource echo: {message}"


@mcp.tool()
def echo_tool(message: str) -> str:
    """Echo a message as a tool"""
    return f"Tool echo: {message}"


@mcp.prompt()
def echo_prompt(message: str) -> str:
    """Create an echo prompt"""
    return f"Please process this message: {message}"
```

### SQLite Explorer

A more complex example showing database integration:

```python
import sqlite3

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("SQLite Explorer")


@mcp.resource("schema://main")
def get_schema() -> str:
    """Provide the database schema as a resource"""
    conn = sqlite3.connect("database.db")
    schema = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall()
    return "\n".join(sql[0] for sql in schema if sql[0])


@mcp.tool()
def query_data(sql: str) -> str:
    """Execute SQL queries safely"""
    conn = sqlite3.connect("database.db")
    try:
        result = conn.execute(sql).fetchall()
        return "\n".join(str(row) for row in result)
    except Exception as e:
        return f"Error: {str(e)}"
```

## Advanced Usage

### Low-Level Server

For more control, you can use the low-level server implementation directly. This gives you full access to the protocol and allows you to customize every aspect of your server, including lifecycle management through the lifespan API:

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fake_database import Database  # Replace with your actual DB type

from mcp.server import Server


@asynccontextmanager
async def server_lifespan(server: Server) -> AsyncIterator[dict]:
    """Manage server startup and shutdown lifecycle."""
    # Initialize resources on startup
    db = await Database.connect()
    try:
        yield {"db": db}
    finally:
        # Clean up on shutdown
        await db.disconnect()


# Pass lifespan to server
server = Server("example-server", lifespan=server_lifespan)


# Access lifespan context in handlers
@server.call_tool()
async def query_db(name: str, arguments: dict) -> list:
    ctx = server.request_context
    db = ctx.lifespan_context["db"]
    return await db.query(arguments["query"])
```

The lifespan API provides:

- A way to initialize resources when the server starts and clean them up when it stops
- Access to initialized resources through the request context in handlers
- Type-safe context passing between lifespan and request handlers

```python
import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# Create a server instance
server = Server("example-server")


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name="example-prompt",
            description="An example prompt template",
            arguments=[
                types.PromptArgument(
                    name="arg1", description="Example argument", required=True
                )
            ],
        )
    ]


@server.get_prompt()
async def handle_get_prompt(
    name: str, arguments: dict[str, str] | None
) -> types.GetPromptResult:
    if name != "example-prompt":
        raise ValueError(f"Unknown prompt: {name}")

    return types.GetPromptResult(
        description="Example prompt",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text="Example prompt text"),
            )
        ],
    )


async def run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="example",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
```

Caution: The `uv run mcp run` and `uv run mcp dev` tool doesn't support low-level server.

#### Structured Output Support

The low-level server supports structured output for tools, allowing you to return both human-readable content and machine-readable structured data. Tools can define an `outputSchema` to validate their structured output:

```python
from types import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("example-server")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="calculate",
            description="Perform mathematical calculations",
            inputSchema={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression"}
                },
                "required": ["expression"],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "result": {"type": "number"},
                    "expression": {"type": "string"},
                },
                "required": ["result", "expression"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "calculate":
        expression = arguments["expression"]
        try:
            result = eval(expression)  # Use a safe math parser
            structured = {"result": result, "expression": expression}

            # low-level server will validate structured output against the tool's
            # output schema, and automatically serialize it into a TextContent block
            # for backwards compatibility with pre-2025-06-18 clients.
            return structured
        except Exception as e:
            raise ValueError(f"Calculation error: {str(e)}")
```

Tools can return data in three ways:

1. **Content only**: Return a list of content blocks (default behavior before spec revision 2025-06-18)
2. **Structured data only**: Return a dictionary that will be serialized to JSON (Introduced in spec revision 2025-06-18)
3. **Both**: Return a tuple of (content, structured_data) preferred option to use for backwards compatibility

When an `outputSchema` is defined, the server automatically validates the structured output against the schema. This ensures type safety and helps catch errors early.

### Writing MCP Clients

The SDK provides a high-level client interface for connecting to MCP servers using various [transports](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports):

```python
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="python",  # Executable
    args=["example_server.py"],  # Optional command line arguments
    env=None,  # Optional environment variables
)


# Optional: create a sampling callback
async def handle_sampling_message(
    message: types.CreateMessageRequestParams,
) -> types.CreateMessageResult:
    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(
            type="text",
            text="Hello, world! from model",
        ),
        model="gpt-3.5-turbo",
        stopReason="endTurn",
    )


async def run():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(
            read, write, sampling_callback=handle_sampling_message
        ) as session:
            # Initialize the connection
            await session.initialize()

            # List available prompts
            prompts = await session.list_prompts()

            # Get a prompt
            prompt = await session.get_prompt(
                "example-prompt", arguments={"arg1": "value"}
            )

            # List available resources
            resources = await session.list_resources()

            # List available tools
            tools = await session.list_tools()

            # Read a resource
            content, mime_type = await session.read_resource("file://some/path")

            # Call a tool
            result = await session.call_tool("tool-name", arguments={"arg1": "value"})


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
```

Clients can also connect using [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http):

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession


async def main():
    # Connect to a streamable HTTP server
    async with streamablehttp_client("example/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        # Create a session using the client streams
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the connection
            await session.initialize()
            # Call a tool
            tool_result = await session.call_tool("echo", {"message": "hello"})
```

### Client Display Utilities

When building MCP clients, the SDK provides utilities to help display human-readable names for tools, resources, and prompts:

```python
from mcp.shared.metadata_utils import get_display_name
from mcp.client.session import ClientSession


async def display_tools(session: ClientSession):
    """Display available tools with human-readable names"""
    tools_response = await session.list_tools()

    for tool in tools_response.tools:
        # get_display_name() returns the title if available, otherwise the name
        display_name = get_display_name(tool)
        print(f"Tool: {display_name}")
        if tool.description:
            print(f"   {tool.description}")


async def display_resources(session: ClientSession):
    """Display available resources with human-readable names"""
    resources_response = await session.list_resources()

    for resource in resources_response.resources:
        display_name = get_display_name(resource)
        print(f"Resource: {display_name} ({resource.uri})")
```

The `get_display_name()` function implements the proper precedence rules for displaying names:

- For tools: `title` > `annotations.title` > `name`
- For other objects: `title` > `name`

This ensures your client UI shows the most user-friendly names that servers provide.

### OAuth Authentication for Clients

The SDK includes [authorization support](https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization) for connecting to protected MCP servers:

```python
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


class CustomTokenStorage(TokenStorage):
    """Simple in-memory token storage implementation."""

    async def get_tokens(self) -> OAuthToken | None:
        pass

    async def set_tokens(self, tokens: OAuthToken) -> None:
        pass

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        pass

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        pass


async def main():
    # Set up OAuth authentication
    oauth_auth = OAuthClientProvider(
        server_url="https://api.example.com",
        client_metadata=OAuthClientMetadata(
            client_name="My Client",
            redirect_uris=["http://localhost:3000/callback"],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=CustomTokenStorage(),
        redirect_handler=lambda url: print(f"Visit: {url}"),
        callback_handler=lambda: ("auth_code", None),
    )

    # Use with streamable HTTP client
    async with streamablehttp_client(
        "https://api.example.com/mcp", auth=oauth_auth
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # Authenticated session ready
```

For a complete working example, see [`examples/clients/simple-auth-client/`](examples/clients/simple-auth-client/).

### MCP Primitives

The MCP protocol defines three core primitives that servers can implement:

| Primitive | Control               | Description                                         | Example Use                  |
|-----------|-----------------------|-----------------------------------------------------|------------------------------|
| Prompts   | User-controlled       | Interactive templates invoked by user choice        | Slash commands, menu options |
| Resources | Application-controlled| Contextual data managed by the client application   | File contents, API responses |
| Tools     | Model-controlled      | Functions exposed to the LLM to take actions        | API calls, data updates      |

### Server Capabilities

MCP servers declare capabilities during initialization:

| Capability   | Feature Flag                 | Description                        |
|--------------|------------------------------|------------------------------------|
| `prompts`    | `listChanged`                | Prompt template management         |
| `resources`  | `subscribe`<br/>`listChanged`| Resource exposure and updates      |
| `tools`      | `listChanged`                | Tool discovery and execution       |
| `logging`    | -                            | Server logging configuration       |
| `completions`| -                            | Argument completion suggestions    |

## Documentation

- [Model Context Protocol documentation](https://modelcontextprotocol.io)
- [Model Context Protocol specification](https://spec.modelcontextprotocol.io)
- [Officially supported servers](https://github.com/modelcontextprotocol/servers)

## Contributing

We are passionate about supporting contributors of all levels of experience and would love to see you get involved in the project. See the [contributing guide](CONTRIBUTING.md) to get started.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
