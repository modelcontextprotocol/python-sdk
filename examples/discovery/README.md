# Example: Progressive Tool Discovery Server

This is a working example of an MCP server that uses **progressive tool discovery** to organize tools into semantic groups and lazy-load them on demand.

All tool groups are defined directly in Python code with **no schema.json files needed**. This is the recommended approach for building production MCP servers with progressive disclosure.

## What This Demonstrates

This server showcases how to:

1. **Organize tools into semantic groups** - Math tools and Weather tools
2. **Enable progressive disclosure** - Only gateway tools are exposed by default (~500 tokens)
3. **Lazy-load tool groups** - When an LLM asks about weather, math tools stay out of context
4. **Save context tokens** - ~77% reduction for servers with many tools
5. **Hybrid mode** - Mix direct tools (e.g., divide) with grouped tools
6. **Real API integration** - Weather tools use live Open-Meteo API and IP geolocation

## Directory Structure

```
discovery/
├── progressive_discovery_server.py   # Main server with discovery enabled (recommended)
├── ai_agent.py                       # Claude-powered agent demonstrating progressive discovery
└── README.md                         # This file
```

## Tool Groups

### Math Tools Group

Provides basic mathematical operations:
- **add** - Add two numbers
- **subtract** - Subtract two numbers
- **multiply** - Multiply two numbers

The **divide** tool is exposed as a direct tool (always visible, not in a group) to demonstrate **hybrid mode**.

### Weather Tools Group

Provides weather and location services using **real APIs**:
- **get_user_location** - Auto-detect user's location using IP geolocation (ipapi.co)
- **geocode_address** - Convert address/city names to coordinates (Open-Meteo Geocoding API)
- **get_forecast** - Get real weather forecast for any coordinates (Open-Meteo Weather API)

## How Progressive Tool Discovery Works

### Traditional Approach (All Tools Upfront)
```
Client: listTools()
Server: [tool1, tool2, tool3, ..., tool100]
        All tool definitions in context (~4,000+ tokens)
LLM: Must consider all tools for every decision
Result: Context bloat, inefficient token usage
```

### Progressive Discovery Approach
```
Step 1: Client calls listTools()
Server: [gateway_tool_1, gateway_tool_2, gateway_tool_3]
        Only group summaries (~300-500 tokens)

Step 2: LLM reads descriptions and decides which group to load
Step 3: LLM calls gateway tool

Step 4: Server returns actual tools from that group
        (~200-400 tokens added, domain-specific)

Step 5: LLM uses the actual tools
Other groups remain unloaded (tokens saved!)
```

### Key Benefit

**Only relevant tools are in context at any time.** When you ask weather questions, math tools stay hidden. This achieves ~77% token savings for large tool sets.

## Running the Server

### Prerequisites
- Python 3.10+
- uv package manager

### Start the Server

```bash
cd examples/discovery
uv run progressive_discovery_server.py
```

The server will start listening on stdio for MCP protocol messages.

## Core Architecture

### Three Main Components

#### 1. Tool Groups
Semantic collections of related tools:
- Organized by function (math, weather, payments, etc.)
- Defined in Python with all tools in one place
- Can contain nested sub-groups

#### 2. Gateway Tools
Auto-generated entry points for each group:
- No input parameters (just presence indicates what's available)
- LLM reads descriptions to understand what tools are in each group
- Calling a gateway tool loads that group's tools into the client's context

#### 3. Server Integration
The MCP Server handles discovery automatically:
- When `enable_discovery_with_groups()` is called, discovery is enabled
- `listTools()` returns only gateway tools initially
- Gateway tool calls trigger loading of actual tools
- `is_discovery_enabled` property tracks whether discovery is active

### Sample Implementation

```python
from mcp.server import Server
from mcp import ToolGroup, Tool

# Define tool groups programmatically
math_group = ToolGroup(
    name="math",
    description="Mathematical operations",
    tools=[
        Tool(name="add", description="Add numbers", inputSchema={...}),
        Tool(name="subtract", description="Subtract numbers", inputSchema={...}),
    ]
)

# Enable discovery
server = Server("my-service")
server.enable_discovery_with_groups([math_group])

# listTools() now returns only gateway tools
# Actual tools load when gateway is called
```

### First `listTools()` Call Example

Server returns **only gateway tools**:
```json
[
  {
    "name": "get_math_tools",
    "description": "Mathematical operations including addition, subtraction, multiplication, and division",
    "inputSchema": {"type": "object", "properties": {}, "required": []}
  },
  {
    "name": "get_weather_tools",
    "description": "Weather information tools including forecasts and alerts",
    "inputSchema": {"type": "object", "properties": {}, "required": []}
  }
]
```

LLM reads descriptions and understands what each group provides.

## Client-Side Experience

When a client connects to a progressive discovery server:

1. **Initial state**: Client gets only gateway tools (~300-500 tokens)
2. **User request**: LLM decides which group is relevant based on descriptions
3. **Gateway call**: LLM calls the gateway tool with no parameters
4. **Tool loading**: Server automatically loads that group's tools
5. **Tool refresh**: Client receives the new tools and updates its context
6. **Tool usage**: LLM uses actual tools from the loaded group
7. **Isolation**: Other groups remain hidden from context

## Is Discovery Enabled?

The Server class provides a property to check discovery status:

```python
server = Server("my-service")
print(server.is_discovery_enabled)  # False by default

# Enable discovery
server.enable_discovery_with_groups([group1, group2])
print(server.is_discovery_enabled)  # True when enabled
```

## Hybrid Mode (Optional)

You can mix approaches:
- **Gateway tools**: Domain-specific tools loaded on demand
- **Direct tools**: High-frequency operations always visible

Example:
- `divide` tool visible everywhere (direct tool)
- `add`, `subtract`, `multiply` in math group (gateway tool)

## Extending the System

To add more tool groups:

1. Define a new `ToolGroup` with related tools
2. Add it to `enable_discovery_with_groups()`
3. The server automatically creates gateway tools
4. No additional handler code needed

## Benefits Demonstrated

- **Token Efficiency** - Only relevant tools in context
- **Scalability** - Easy to add many tool groups
- **LLM Autonomy** - LLM decides which tools to load
- **Clean Architecture** - Semantic grouping is explicit
- **Backward Compatible** - No changes to existing MCP protocol

## Further Reading

- [CLAUDE.md](../../.claude/CLAUDE.md) - Full specification
- [PHASE_1_IMPLEMENTATION.md](../../.claude/PHASE_1_IMPLEMENTATION.md) - Core system
- [PHASE_2_IMPLEMENTATION.md](../../.claude/PHASE_2_IMPLEMENTATION.md) - Server integration

## Key Takeaways

- **Progressive discovery is optional** - `is_discovery_enabled` controls whether it's active
- **Backward compatible** - Existing MCP servers work unchanged
- **Tool groups are flexible** - Define any semantic grouping that makes sense for your domain
- **Client handling is automatic** - Refresh happens transparently via notifications
- **Hybrid mode possible** - Mix direct and grouped tools as needed
