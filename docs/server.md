# Building MCP Servers

## Core Concepts

### Server

The FastMCP server is your core interface to the MCP protocol. It handles connection management, protocol compliance, and message routing:

<!-- snippet-source examples/snippets/servers/lifespan_example.py -->
```python
"""Example showing lifespan support for startup/shutdown with strong typing."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession


# Mock database class for example
class Database:
    """Mock database class for example."""

    @classmethod
    async def connect(cls) -> "Database":
        """Connect to database."""
        return cls()

    async def disconnect(self) -> None:
        """Disconnect from database."""
        pass

    def query(self) -> str:
        """Execute a query."""
        return "Query result"


@dataclass
class AppContext:
    """Application context with typed dependencies."""

    db: Database


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle with type-safe context."""
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
def query_db(ctx: Context[ServerSession, AppContext]) -> str:
    """Tool that uses initialized resources."""
    db = ctx.request_context.lifespan_context.db
    return db.query()
```

_Full example: [examples/snippets/servers/lifespan_example.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/lifespan_example.py)_
<!-- /snippet-source -->

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

#### Resource Templates and Template Reading

Resources with URI parameters (e.g., `{name}`) are registered as templates. When a client reads a templated resource, the URI parameters are extracted and passed to the function:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Template Example")


@mcp.resource("users://{user_id}/profile")
def get_user_profile(user_id: str) -> str:
    """Read a specific user's profile. The user_id is extracted from the URI."""
    return f'{{"user_id": "{user_id}", "name": "User {user_id}"}}'
```

Clients read a template resource by providing a concrete URI:

```python
# Client-side: read a template resource with a concrete URI
content = await session.read_resource("users://alice/profile")
```

Templates with multiple parameters work the same way:

```python
@mcp.resource("repos://{owner}/{repo}/readme")
def get_readme(owner: str, repo: str) -> str:
    """Each URI parameter becomes a function argument."""
    return f"README for {owner}/{repo}"
```

#### Binary Resources

Resources can return binary data by returning `bytes` instead of `str`. Set the `mime_type` to indicate the content type:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Binary Resource Example")


@mcp.resource("images://logo.png", mime_type="image/png")
def get_logo() -> bytes:
    """Return a binary image resource."""
    with open("logo.png", "rb") as f:
        return f.read()
```

Binary content is automatically base64-encoded and returned as `BlobResourceContents` in the MCP response.

#### Resource Subscriptions

Clients can subscribe to resource updates. Use the low-level server API to handle subscription and unsubscription requests:

```python
import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Subscription Example")

subscriptions: dict[str, set[str]] = {}  # uri -> set of session ids


@server.subscribe_resource()
async def handle_subscribe(uri) -> None:
    """Handle a client subscribing to a resource."""
    subscriptions.setdefault(str(uri), set()).add("current_session")


@server.unsubscribe_resource()
async def handle_unsubscribe(uri) -> None:
    """Handle a client unsubscribing from a resource."""
    if str(uri) in subscriptions:
        subscriptions[str(uri)].discard("current_session")
```

When a subscribed resource changes, notify clients with `send_resource_updated()`:

```python
from pydantic import AnyUrl

# After modifying resource data:
await session.send_resource_updated(AnyUrl("resource://my-resource"))
```

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

Tools can optionally receive a Context object by including a parameter with the `Context` type annotation. This context is automatically injected by the FastMCP framework and provides access to MCP capabilities:

<!-- snippet-source examples/snippets/servers/tool_progress.py -->
```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP(name="Progress Example")


@mcp.tool()
async def long_running_task(task_name: str, ctx: Context[ServerSession, None], steps: int = 5) -> str:
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

##### Advanced: Direct CallToolResult

For full control over tool responses including the `_meta` field (for passing data to client applications without exposing it to the model), you can return `CallToolResult` directly:

<!-- snippet-source examples/snippets/servers/direct_call_tool_result.py -->
```python
"""Example showing direct CallToolResult return for advanced control."""

from typing import Annotated

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

mcp = FastMCP("CallToolResult Example")


class ValidationModel(BaseModel):
    """Model for validating structured output."""

    status: str
    data: dict[str, int]


@mcp.tool()
def advanced_tool() -> CallToolResult:
    """Return CallToolResult directly for full control including _meta field."""
    return CallToolResult(
        content=[TextContent(type="text", text="Response visible to the model")],
        _meta={"hidden": "data for client applications only"},
    )


@mcp.tool()
def validated_tool() -> Annotated[CallToolResult, ValidationModel]:
    """Return CallToolResult with structured output validation."""
    return CallToolResult(
        content=[TextContent(type="text", text="Validated response")],
        structuredContent={"status": "success", "data": {"result": 42}},
        _meta={"internal": "metadata"},
    )


@mcp.tool()
def empty_result_tool() -> CallToolResult:
    """For empty results, return CallToolResult with empty content."""
    return CallToolResult(content=[])
```

_Full example: [examples/snippets/servers/direct_call_tool_result.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/direct_call_tool_result.py)_
<!-- /snippet-source -->

**Important:** `CallToolResult` must always be returned (no `Optional` or `Union`). For empty results, use `CallToolResult(content=[])`. For optional simple types, use `str | None` without `CallToolResult`.

<!-- snippet-source examples/snippets/servers/structured_output.py -->
```python
"""Example showing structured output with tools."""

from typing import TypedDict

from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Structured Output Example")


# Using Pydantic models for rich structured data
class WeatherData(BaseModel):
    """Weather information structure."""

    temperature: float = Field(description="Temperature in Celsius")
    humidity: float = Field(description="Humidity percentage")
    condition: str
    wind_speed: float


@mcp.tool()
def get_weather(city: str) -> WeatherData:
    """Get weather for a city - returns structured data."""
    # Simulated weather data
    return WeatherData(
        temperature=22.5,
        humidity=45.0,
        condition="sunny",
        wind_speed=5.2,
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
    def __init__(self, setting1, setting2):  # type: ignore[reportMissingParameterType]
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

_Full example: [examples/snippets/servers/structured_output.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/structured_output.py)_
<!-- /snippet-source -->

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

#### Prompts with Embedded Resources

Prompts can include embedded resources to provide file contents or data alongside the conversation messages:

```python
import mcp.types as types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base

mcp = FastMCP("Embedded Resource Prompt Example")


@mcp.prompt()
def review_file(filename: str) -> list[base.Message]:
    """Review a file with its contents embedded."""
    file_content = open(filename).read()
    return [
        base.UserMessage(
            content=types.TextContent(type="text", text=f"Please review {filename}:"),
        ),
        base.UserMessage(
            content=types.EmbeddedResource(
                type="resource",
                resource=types.TextResourceContents(
                    uri=f"file://{filename}",
                    text=file_content,
                    mimeType="text/plain",
                ),
            ),
        ),
    ]
```

#### Prompts with Image Content

Prompts can include images using `ImageContent` or the `Image` helper class:

```python
import mcp.types as types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base
from mcp.server.fastmcp.utilities.types import Image

mcp = FastMCP("Image Prompt Example")


@mcp.prompt()
def describe_image(image_path: str) -> list[base.Message]:
    """Prompt that includes an image for analysis."""
    img = Image(path=image_path)
    return [
        base.UserMessage(
            content=types.TextContent(type="text", text="Describe this image:"),
        ),
        base.UserMessage(
            content=img.to_image_content(),
        ),
    ]
```

#### Prompt Change Notifications

When your server dynamically adds or removes prompts, notify connected clients:

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Dynamic Prompts")


@mcp.tool()
async def update_prompts(ctx: Context[ServerSession, None]) -> str:
    """Update available prompts and notify clients."""
    # ... modify prompts ...
    await ctx.session.send_prompt_list_changed()
    return "Prompts updated"
```

### Icons

MCP servers can provide icons for UI display. Icons can be added to the server implementation, tools, resources, and prompts:

```python
from mcp.server.fastmcp import FastMCP, Icon

# Create an icon from a file path or URL
icon = Icon(
    src="icon.png",
    mimeType="image/png",
    sizes="64x64"
)

# Add icons to server
mcp = FastMCP(
    "My Server",
    website_url="https://example.com",
    icons=[icon]
)

# Add icons to tools, resources, and prompts
@mcp.tool(icons=[icon])
def my_tool():
    """Tool with an icon."""
    return "result"

@mcp.resource("demo://resource", icons=[icon])
def my_resource():
    """Resource with an icon."""
    return "content"
```

_Full example: [examples/fastmcp/icons_demo.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/fastmcp/icons_demo.py)_

### Images

FastMCP provides an `Image` class that automatically handles image data:

<!-- snippet-source examples/snippets/servers/images.py -->
```python
"""Example showing image handling with FastMCP."""

from PIL import Image as PILImage

from mcp.server.fastmcp import FastMCP, Image

mcp = FastMCP("Image Example")


@mcp.tool()
def create_thumbnail(image_path: str) -> Image:
    """Create a thumbnail from an image"""
    img = PILImage.open(image_path)
    img.thumbnail((100, 100))
    return Image(data=img.tobytes(), format="png")
```

_Full example: [examples/snippets/servers/images.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/images.py)_
<!-- /snippet-source -->

### Audio

FastMCP provides an `Audio` class for returning audio data from tools, similar to `Image`:

```python
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Audio

mcp = FastMCP("Audio Example")


@mcp.tool()
def get_audio_from_file(file_path: str) -> Audio:
    """Return audio from a file path (format auto-detected from extension)."""
    return Audio(path=file_path)


@mcp.tool()
def get_audio_from_bytes(raw_audio: bytes) -> Audio:
    """Return audio from raw bytes with explicit format."""
    return Audio(data=raw_audio, format="wav")
```

The `Audio` class accepts `path` or `data` (mutually exclusive) and an optional `format` string. Supported formats include `wav`, `mp3`, `ogg`, `flac`, `aac`, and `m4a`. When using a file path, the MIME type is inferred from the file extension.

### Embedded Resource Results

Tools can return `EmbeddedResource` to attach file contents or data inline in the result:

```python
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, TextResourceContents

mcp = FastMCP("Embedded Resource Example")


@mcp.tool()
def read_config(path: str) -> EmbeddedResource:
    """Read a config file and return it as an embedded resource."""
    with open(path) as f:
        content = f.read()
    return EmbeddedResource(
        type="resource",
        resource=TextResourceContents(
            uri=f"file://{path}",
            text=content,
            mimeType="application/json",
        ),
    )
```

For binary embedded resources, use `BlobResourceContents` with base64-encoded data:

```python
import base64

from mcp.types import BlobResourceContents, EmbeddedResource


@mcp.tool()
def read_binary_file(path: str) -> EmbeddedResource:
    """Read a binary file and return it as an embedded resource."""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return EmbeddedResource(
        type="resource",
        resource=BlobResourceContents(
            uri=f"file://{path}",
            blob=data,
            mimeType="application/octet-stream",
        ),
    )
```

### Tool Change Notifications

When your server dynamically adds or removes tools at runtime, notify connected clients so they can refresh their tool list:

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Dynamic Tools")


@mcp.tool()
async def register_plugin(name: str, ctx: Context[ServerSession, None]) -> str:
    """Dynamically register a new tool and notify the client."""
    # ... register the plugin's tools ...

    # Notify the client that the tool list has changed
    await ctx.session.send_tool_list_changed()

    return f"Plugin '{name}' registered"
```

### Context

The Context object is automatically injected into tool and resource functions that request it via type hints. It provides access to MCP capabilities like logging, progress reporting, resource reading, user interaction, and request metadata.

#### Getting Context in Functions

To use context in a tool or resource function, add a parameter with the `Context` type annotation:

```python
from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP(name="Context Example")


@mcp.tool()
async def my_tool(x: int, ctx: Context) -> str:
    """Tool that uses context capabilities."""
    # The context parameter can have any name as long as it's type-annotated
    return await process_with_context(x, ctx)
```

#### Context Properties and Methods

The Context object provides the following capabilities:

- `ctx.request_id` - Unique ID for the current request
- `ctx.client_id` - Client ID if available
- `ctx.fastmcp` - Access to the FastMCP server instance (see [FastMCP Properties](#fastmcp-properties))
- `ctx.session` - Access to the underlying session for advanced communication (see [Session Properties and Methods](#session-properties-and-methods))
- `ctx.request_context` - Access to request-specific data and lifespan resources (see [Request Context Properties](#request-context-properties))
- `await ctx.debug(message)` - Send debug log message
- `await ctx.info(message)` - Send info log message
- `await ctx.warning(message)` - Send warning log message
- `await ctx.error(message)` - Send error log message
- `await ctx.log(level, message, logger_name=None)` - Send log with custom level
- `await ctx.report_progress(progress, total=None, message=None)` - Report operation progress
- `await ctx.read_resource(uri)` - Read a resource by URI
- `await ctx.elicit(message, schema)` - Request additional information from user with validation

<!-- snippet-source examples/snippets/servers/tool_progress.py -->
```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP(name="Progress Example")


@mcp.tool()
async def long_running_task(task_name: str, ctx: Context[ServerSession, None], steps: int = 5) -> str:
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

<!-- snippet-source examples/snippets/clients/completion_client.py -->
```python
"""
cd to the `examples/snippets` directory and run:
    uv run completion-client
"""

import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import PromptReference, ResourceTemplateReference

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="uv",  # Using uv to run the server
    args=["run", "server", "completion", "stdio"],  # Server with completion support
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


async def run():
    """Run the completion client example."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()

            # List available resource templates
            templates = await session.list_resource_templates()
            print("Available resource templates:")
            for template in templates.resourceTemplates:
                print(f"  - {template.uriTemplate}")

            # List available prompts
            prompts = await session.list_prompts()
            print("\nAvailable prompts:")
            for prompt in prompts.prompts:
                print(f"  - {prompt.name}")

            # Complete resource template arguments
            if templates.resourceTemplates:
                template = templates.resourceTemplates[0]
                print(f"\nCompleting arguments for resource template: {template.uriTemplate}")

                # Complete without context
                result = await session.complete(
                    ref=ResourceTemplateReference(type="ref/resource", uri=template.uriTemplate),
                    argument={"name": "owner", "value": "model"},
                )
                print(f"Completions for 'owner' starting with 'model': {result.completion.values}")

                # Complete with context - repo suggestions based on owner
                result = await session.complete(
                    ref=ResourceTemplateReference(type="ref/resource", uri=template.uriTemplate),
                    argument={"name": "repo", "value": ""},
                    context_arguments={"owner": "modelcontextprotocol"},
                )
                print(f"Completions for 'repo' with owner='modelcontextprotocol': {result.completion.values}")

            # Complete prompt arguments
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
```

_Full example: [examples/snippets/clients/completion_client.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/clients/completion_client.py)_
<!-- /snippet-source -->
### Elicitation

Request additional information from users. This example shows an Elicitation during a Tool Call:

<!-- snippet-source examples/snippets/servers/elicitation.py -->
```python
"""Elicitation examples demonstrating form and URL mode elicitation.

Form mode elicitation collects structured, non-sensitive data through a schema.
URL mode elicitation directs users to external URLs for sensitive operations
like OAuth flows, credential collection, or payment processing.
"""

import uuid

from pydantic import BaseModel, Field

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import ElicitRequestURLParams

mcp = FastMCP(name="Elicitation Example")


class BookingPreferences(BaseModel):
    """Schema for collecting user preferences."""

    checkAlternative: bool = Field(description="Would you like to check another date?")
    alternativeDate: str = Field(
        default="2024-12-26",
        description="Alternative date (YYYY-MM-DD)",
    )


@mcp.tool()
async def book_table(date: str, time: str, party_size: int, ctx: Context[ServerSession, None]) -> str:
    """Book a table with date availability check.

    This demonstrates form mode elicitation for collecting non-sensitive user input.
    """
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


@mcp.tool()
async def secure_payment(amount: float, ctx: Context[ServerSession, None]) -> str:
    """Process a secure payment requiring URL confirmation.

    This demonstrates URL mode elicitation using ctx.elicit_url() for
    operations that require out-of-band user interaction.
    """
    elicitation_id = str(uuid.uuid4())

    result = await ctx.elicit_url(
        message=f"Please confirm payment of ${amount:.2f}",
        url=f"https://payments.example.com/confirm?amount={amount}&id={elicitation_id}",
        elicitation_id=elicitation_id,
    )

    if result.action == "accept":
        # In a real app, the payment confirmation would happen out-of-band
        # and you'd verify the payment status from your backend
        return f"Payment of ${amount:.2f} initiated - check your browser to complete"
    elif result.action == "decline":
        return "Payment declined by user"
    return "Payment cancelled"


@mcp.tool()
async def connect_service(service_name: str, ctx: Context[ServerSession, None]) -> str:
    """Connect to a third-party service requiring OAuth authorization.

    This demonstrates the "throw error" pattern using UrlElicitationRequiredError.
    Use this pattern when the tool cannot proceed without user authorization.
    """
    elicitation_id = str(uuid.uuid4())

    # Raise UrlElicitationRequiredError to signal that the client must complete
    # a URL elicitation before this request can be processed.
    # The MCP framework will convert this to a -32042 error response.
    raise UrlElicitationRequiredError(
        [
            ElicitRequestURLParams(
                mode="url",
                message=f"Authorization required to connect to {service_name}",
                url=f"https://{service_name}.example.com/oauth/authorize?elicit={elicitation_id}",
                elicitationId=elicitation_id,
            )
        ]
    )
```

_Full example: [examples/snippets/servers/elicitation.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/elicitation.py)_
<!-- /snippet-source -->

Elicitation schemas support default values for all field types. Default values are automatically included in the JSON schema sent to clients, allowing them to pre-populate forms.

The `elicit()` method returns an `ElicitationResult` with:

- `action`: "accept", "decline", or "cancel"
- `data`: The validated response (only when accepted)
- `validation_error`: Any validation error message

#### Elicitation with Enum Values

To present a dropdown or selection list in elicitation forms, use `json_schema_extra` with an `enum` key on a `str` field. Do not use `Literal` -- use a plain `str` field with the enum constraint in the JSON schema:

```python
from pydantic import BaseModel, Field

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Enum Elicitation Example")


class ColorPreference(BaseModel):
    color: str = Field(
        description="Pick your favorite color",
        json_schema_extra={"enum": ["red", "green", "blue", "yellow"]},
    )


@mcp.tool()
async def pick_color(ctx: Context[ServerSession, None]) -> str:
    """Ask the user to pick a color from a list."""
    result = await ctx.elicit(
        message="Choose a color:",
        schema=ColorPreference,
    )
    if result.action == "accept":
        return f"You picked: {result.data.color}"
    return "No color selected"
```

#### Elicitation Complete Notification

For URL mode elicitations, send a completion notification after the out-of-band interaction finishes. This tells the client that the elicitation is done and it may retry any blocked requests:

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Elicit Complete Example")


@mcp.tool()
async def handle_oauth_callback(
    elicitation_id: str, ctx: Context[ServerSession, None]
) -> str:
    """Called when OAuth flow completes out-of-band."""
    # ... process the callback ...

    # Notify the client that the elicitation is done
    await ctx.session.send_elicit_complete(elicitation_id)

    return "Authorization complete"
```

### Sampling

Tools can interact with LLMs through sampling (generating text):

<!-- snippet-source examples/snippets/servers/sampling.py -->
```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.types import SamplingMessage, TextContent

mcp = FastMCP(name="Sampling Example")


@mcp.tool()
async def generate_poem(topic: str, ctx: Context[ServerSession, None]) -> str:
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

    # Since we're not passing tools param, result.content is single content
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
from mcp.server.session import ServerSession

mcp = FastMCP(name="Notifications Example")


@mcp.tool()
async def process_data(data: str, ctx: Context[ServerSession, None]) -> str:
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

#### Setting the Logging Level

Clients can request a minimum logging level via `logging/setLevel`. Use the low-level server API to handle this:

```python
import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Logging Level Example")

current_level: types.LoggingLevel = "warning"


@server.set_logging_level()
async def handle_set_level(level: types.LoggingLevel) -> None:
    """Handle client request to change the logging level."""
    global current_level
    current_level = level
```

When this handler is registered, the server automatically declares the `logging` capability during initialization.

### Authentication

For OAuth 2.1 server and client authentication, see [Authorization](authorization.md).

### FastMCP Properties

The FastMCP server instance accessible via `ctx.fastmcp` provides access to server configuration and metadata:

- `ctx.fastmcp.name` - The server's name as defined during initialization
- `ctx.fastmcp.instructions` - Server instructions/description provided to clients
- `ctx.fastmcp.website_url` - Optional website URL for the server
- `ctx.fastmcp.icons` - Optional list of icons for UI display
- `ctx.fastmcp.settings` - Complete server configuration object containing:
  - `debug` - Debug mode flag
  - `log_level` - Current logging level
  - `host` and `port` - Server network configuration
  - `mount_path`, `sse_path`, `streamable_http_path` - Transport paths
  - `stateless_http` - Whether the server operates in stateless mode
  - And other configuration options

```python
@mcp.tool()
def server_info(ctx: Context) -> dict:
    """Get information about the current server."""
    return {
        "name": ctx.fastmcp.name,
        "instructions": ctx.fastmcp.instructions,
        "debug_mode": ctx.fastmcp.settings.debug,
        "log_level": ctx.fastmcp.settings.log_level,
        "host": ctx.fastmcp.settings.host,
        "port": ctx.fastmcp.settings.port,
    }
```

### Session Properties and Methods

The session object accessible via `ctx.session` provides advanced control over client communication:

- `ctx.session.client_params` - Client initialization parameters and declared capabilities
- `await ctx.session.send_log_message(level, data, logger)` - Send log messages with full control
- `await ctx.session.create_message(messages, max_tokens)` - Request LLM sampling/completion
- `await ctx.session.send_progress_notification(token, progress, total, message)` - Direct progress updates
- `await ctx.session.send_resource_updated(uri)` - Notify clients that a specific resource changed
- `await ctx.session.send_resource_list_changed()` - Notify clients that the resource list changed
- `await ctx.session.send_tool_list_changed()` - Notify clients that the tool list changed
- `await ctx.session.send_prompt_list_changed()` - Notify clients that the prompt list changed

```python
@mcp.tool()
async def notify_data_update(resource_uri: str, ctx: Context) -> str:
    """Update data and notify clients of the change."""
    # Perform data update logic here

    # Notify clients that this specific resource changed
    await ctx.session.send_resource_updated(AnyUrl(resource_uri))

    # If this affects the overall resource list, notify about that too
    await ctx.session.send_resource_list_changed()

    return f"Updated {resource_uri} and notified clients"
```

### Request Context Properties

The request context accessible via `ctx.request_context` contains request-specific information and resources:

- `ctx.request_context.lifespan_context` - Access to resources initialized during server startup
  - Database connections, configuration objects, shared services
  - Type-safe access to resources defined in your server's lifespan function
- `ctx.request_context.meta` - Request metadata from the client including:
  - `progressToken` - Token for progress notifications
  - Other client-provided metadata
- `ctx.request_context.request` - The original MCP request object for advanced processing
- `ctx.request_context.request_id` - Unique identifier for this request

```python
# Example with typed lifespan context
@dataclass
class AppContext:
    db: Database
    config: AppConfig

@mcp.tool()
def query_with_config(query: str, ctx: Context) -> str:
    """Execute a query using shared database and configuration."""
    # Access typed lifespan context
    app_ctx: AppContext = ctx.request_context.lifespan_context

    # Use shared resources
    connection = app_ctx.db
    settings = app_ctx.config

    # Execute query with configuration
    result = connection.execute(query, timeout=settings.query_timeout)
    return str(result)
```

_Full lifespan example: [examples/snippets/servers/lifespan_example.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/lifespan_example.py)_

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

<!-- snippet-source examples/snippets/servers/direct_execution.py -->
```python
"""Example showing direct execution of an MCP server.

This is the simplest way to run an MCP server directly.
cd to the `examples/snippets` directory and run:
    uv run direct-execution-server
    or
    python servers/direct_execution.py
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My App")


@mcp.tool()
def hello(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"


def main():
    """Entry point for the direct execution server."""
    mcp.run()


if __name__ == "__main__":
    main()
```

_Full example: [examples/snippets/servers/direct_execution.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/direct_execution.py)_
<!-- /snippet-source -->

Run it with:

```bash
python servers/direct_execution.py
# or
uv run mcp run servers/direct_execution.py
```

Note that `uv run mcp run` or `uv run mcp dev` only supports server using FastMCP and not the low-level server variant.

### Streamable HTTP Transport

> **Note**: Streamable HTTP transport is the recommended transport for production deployments. Use `stateless_http=True` and `json_response=True` for optimal scalability.

<!-- snippet-source examples/snippets/servers/streamable_config.py -->
```python
"""
Run from the repository root:
    uv run examples/snippets/servers/streamable_config.py
"""

from mcp.server.fastmcp import FastMCP

# Stateless server with JSON responses (recommended)
mcp = FastMCP("StatelessServer", stateless_http=True, json_response=True)

# Other configuration options:
# Stateless server with SSE streaming responses
# mcp = FastMCP("StatelessServer", stateless_http=True)

# Stateful server with session persistence
# mcp = FastMCP("StatefulServer")


# Add a simple tool to demonstrate the server
@mcp.tool()
def greet(name: str = "World") -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"


# Run server with streamable_http transport
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

_Full example: [examples/snippets/servers/streamable_config.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/streamable_config.py)_
<!-- /snippet-source -->

You can mount multiple FastMCP servers in a Starlette application:

<!-- snippet-source examples/snippets/servers/streamable_starlette_mount.py -->
```python
"""
Run from the repository root:
    uvicorn examples.snippets.servers.streamable_starlette_mount:app --reload
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP

# Create the Echo server
echo_mcp = FastMCP(name="EchoServer", stateless_http=True, json_response=True)


@echo_mcp.tool()
def echo(message: str) -> str:
    """A simple echo tool"""
    return f"Echo: {message}"


# Create the Math server
math_mcp = FastMCP(name="MathServer", stateless_http=True, json_response=True)


@math_mcp.tool()
def add_two(n: int) -> int:
    """Tool to add two to the input"""
    return n + 2


# Create a combined lifespan to manage both session managers
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(echo_mcp.session_manager.run())
        await stack.enter_async_context(math_mcp.session_manager.run())
        yield


# Create the Starlette app and mount the MCP servers
app = Starlette(
    routes=[
        Mount("/echo", echo_mcp.streamable_http_app()),
        Mount("/math", math_mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)

# Note: Clients connect to http://localhost:8000/echo/mcp and http://localhost:8000/math/mcp
# To mount at the root of each path (e.g., /echo instead of /echo/mcp):
# echo_mcp.settings.streamable_http_path = "/"
# math_mcp.settings.streamable_http_path = "/"
```

_Full example: [examples/snippets/servers/streamable_starlette_mount.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/streamable_starlette_mount.py)_
<!-- /snippet-source -->

For low level server with Streamable HTTP implementations, see:

- Stateful server: [`examples/servers/simple-streamablehttp/`](examples/servers/simple-streamablehttp/)
- Stateless server: [`examples/servers/simple-streamablehttp-stateless/`](examples/servers/simple-streamablehttp-stateless/)

The streamable HTTP transport supports:

- Stateful and stateless operation modes
- Resumability with event stores
- JSON or SSE response formats
- Better scalability for multi-node deployments

#### CORS Configuration for Browser-Based Clients

If you'd like your server to be accessible by browser-based MCP clients, you'll need to configure CORS headers. The `Mcp-Session-Id` header must be exposed for browser clients to access it:

```python
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware

# Create your Starlette app first
starlette_app = Starlette(routes=[...])

# Then wrap it with CORS middleware
starlette_app = CORSMiddleware(
    starlette_app,
    allow_origins=["*"],  # Configure appropriately for production
    allow_methods=["GET", "POST", "DELETE"],  # MCP streamable HTTP methods
    expose_headers=["Mcp-Session-Id"],
)
```

This configuration is necessary because:

- The MCP streamable HTTP transport uses the `Mcp-Session-Id` header for session management
- Browsers restrict access to response headers unless explicitly exposed via CORS
- Without this configuration, browser-based clients won't be able to read the session ID from initialization responses

### Mounting to an Existing ASGI Server

By default, SSE servers are mounted at `/sse` and Streamable HTTP servers are mounted at `/mcp`. You can customize these paths using the methods described below.

For more information on mounting applications in Starlette, see the [Starlette documentation](https://www.starlette.io/routing/#submounting-routes).

#### StreamableHTTP servers

You can mount the StreamableHTTP server to an existing ASGI server using the `streamable_http_app` method. This allows you to integrate the StreamableHTTP server with other ASGI applications.

##### Basic mounting

<!-- snippet-source examples/snippets/servers/streamable_http_basic_mounting.py -->
```python
"""
Basic example showing how to mount StreamableHTTP server in Starlette.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_basic_mounting:app --reload
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP

# Create MCP server
mcp = FastMCP("My App", json_response=True)


@mcp.tool()
def hello() -> str:
    """A simple hello tool"""
    return "Hello from MCP!"


# Create a lifespan context manager to run the session manager
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield


# Mount the StreamableHTTP server to the existing ASGI server
app = Starlette(
    routes=[
        Mount("/", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)
```

_Full example: [examples/snippets/servers/streamable_http_basic_mounting.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/streamable_http_basic_mounting.py)_
<!-- /snippet-source -->

##### Host-based routing

<!-- snippet-source examples/snippets/servers/streamable_http_host_mounting.py -->
```python
"""
Example showing how to mount StreamableHTTP server using Host-based routing.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_host_mounting:app --reload
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Host

from mcp.server.fastmcp import FastMCP

# Create MCP server
mcp = FastMCP("MCP Host App", json_response=True)


@mcp.tool()
def domain_info() -> str:
    """Get domain-specific information"""
    return "This is served from mcp.acme.corp"


# Create a lifespan context manager to run the session manager
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield


# Mount using Host-based routing
app = Starlette(
    routes=[
        Host("mcp.acme.corp", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)
```

_Full example: [examples/snippets/servers/streamable_http_host_mounting.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/streamable_http_host_mounting.py)_
<!-- /snippet-source -->

##### Multiple servers with path configuration

<!-- snippet-source examples/snippets/servers/streamable_http_multiple_servers.py -->
```python
"""
Example showing how to mount multiple StreamableHTTP servers with path configuration.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_multiple_servers:app --reload
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP

# Create multiple MCP servers
api_mcp = FastMCP("API Server", json_response=True)
chat_mcp = FastMCP("Chat Server", json_response=True)


@api_mcp.tool()
def api_status() -> str:
    """Get API status"""
    return "API is running"


@chat_mcp.tool()
def send_message(message: str) -> str:
    """Send a chat message"""
    return f"Message sent: {message}"


# Configure servers to mount at the root of each path
# This means endpoints will be at /api and /chat instead of /api/mcp and /chat/mcp
api_mcp.settings.streamable_http_path = "/"
chat_mcp.settings.streamable_http_path = "/"


# Create a combined lifespan to manage both session managers
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(api_mcp.session_manager.run())
        await stack.enter_async_context(chat_mcp.session_manager.run())
        yield


# Mount the servers
app = Starlette(
    routes=[
        Mount("/api", app=api_mcp.streamable_http_app()),
        Mount("/chat", app=chat_mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)
```

_Full example: [examples/snippets/servers/streamable_http_multiple_servers.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/streamable_http_multiple_servers.py)_
<!-- /snippet-source -->

##### Path configuration at initialization

<!-- snippet-source examples/snippets/servers/streamable_http_path_config.py -->
```python
"""
Example showing path configuration during FastMCP initialization.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_path_config:app --reload
"""

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP

# Configure streamable_http_path during initialization
# This server will mount at the root of wherever it's mounted
mcp_at_root = FastMCP(
    "My Server",
    json_response=True,
    streamable_http_path="/",
)


@mcp_at_root.tool()
def process_data(data: str) -> str:
    """Process some data"""
    return f"Processed: {data}"


# Mount at /process - endpoints will be at /process instead of /process/mcp
app = Starlette(
    routes=[
        Mount("/process", app=mcp_at_root.streamable_http_app()),
    ]
)
```

_Full example: [examples/snippets/servers/streamable_http_path_config.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/streamable_http_path_config.py)_
<!-- /snippet-source -->

#### SSE servers

> **Note**: SSE transport is being superseded by [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http).

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

## Advanced Usage

For the low-level server API, pagination, and direct handler registration, see [Low-Level Server](low-level-server.md).
