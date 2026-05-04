# Research Agent: Key Features

The `examples/research-agent` example shows how to build a research agent on top of the MCP Python SDK. It demonstrates three features that are common in production agent workflows:

- **Collaborative Planning** — the agent presents a step-by-step research plan for user approval before doing any work.
- **MCP Support** — the agent connects to remote MCP servers at startup and incorporates their tools into the research workflow.
- **Visualizations** — the agent extracts numeric findings from research results and returns a chart as a base64-encoded SVG image.

All three features are implemented using standard MCP primitives already present in the SDK (tasks, elicitation, sampling, `ClientSessionGroup`, and `ImageContent`).

---

## Running the example

```bash
cd examples/research-agent
uv run mcp-research-agent --port 8000
```

The server listens at `http://127.0.0.1:8000/mcp`.

---

## Feature 1 — Collaborative Planning

### What it does

When a client calls the `research` tool with `"collaborative_planning": true`, the agent:

1. Uses LLM sampling (`create_message`) to draft a step-by-step research plan.
2. Presents the plan to the user via **elicitation** and waits for approval.
3. Proceeds with research only if the user approves; otherwise returns a cancellation message.

This gives users full visibility into — and control over — what the agent intends to do before it expends any effort.

### How to use it

```json
{
  "name": "research",
  "arguments": {
    "query": "Latest advances in battery technology",
    "collaborative_planning": true
  }
}
```

The client receives an elicitation request with a schema like:

```json
{
  "type": "object",
  "properties": {
    "approved": { "type": "boolean" },
    "feedback": { "type": "string" }
  },
  "required": ["approved"]
}
```

Set `"approved": true` (and optionally provide `"feedback"`) to continue; any other response cancels the task.

### Implementation

Collaborative planning uses the existing [Tasks and Elicitation](experimental/tasks.md) infrastructure:

```python
elicit_result = await task.elicit(
    message=f"Research Plan\n{'─' * 40}\n{plan_text}\n\nApprove to begin?",
    requestedSchema={
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "feedback": {"type": "string"},
        },
        "required": ["approved"],
    },
)

if not (elicit_result.action == "accept" and elicit_result.content.get("approved")):
    return types.CallToolResult(content=[types.TextContent(type="text", text="Research cancelled.")])
```

---

## Feature 2 — MCP Support

### What it does

The research agent connects to one or more **remote MCP servers** at startup. Their tools are discovered, aggregated, and queried during the research task — giving the agent access to private data sources, internal APIs, or custom domain tools.

### Configuration

Set the `MCP_SERVERS` environment variable to a JSON array of server descriptors before starting the server:

```bash
# stdio server
MCP_SERVERS='[{"type":"stdio","command":"python","args":["-m","my_data_server"]}]' \
  uv run mcp-research-agent

# SSE server
MCP_SERVERS='[{"type":"sse","url":"http://internal-api/sse"}]' \
  uv run mcp-research-agent

# StreamableHTTP server
MCP_SERVERS='[{"type":"streamable_http","url":"http://internal-api/mcp"}]' \
  uv run mcp-research-agent

# Multiple servers
MCP_SERVERS='[
  {"type":"stdio","command":"python","args":["-m","my_db_server"]},
  {"type":"sse","url":"http://analytics/sse"}
]' uv run mcp-research-agent
```

### Inspecting connected tools

Use the `list_mcp_tools` tool to see what is available:

```json
{ "name": "list_mcp_tools", "arguments": {} }
```

### Implementation

`ClientSessionGroup` manages concurrent connections to all configured servers. It aggregates their tools into a single `dict[str, Tool]`:

```python
async with ClientSessionGroup() as group:
    for params in server_params:
        await group.connect_to_server(params)

    # Call a tool from any connected server by name
    result = await group.call_tool("my_tool", {"arg": "value"})
```

The research agent stores the group as a module-level reference during the ASGI lifespan, so all task handlers can reach it.

---

## Feature 3 — Visualizations

### What it does

When `"visualization": "auto"` is passed, the agent:

1. Scans the research summary for labelled numeric values (e.g. `"Market size: $4.5B"`, `"Growth rate: 12%"`).
2. Generates a bar chart from the extracted metrics using pure-Python SVG.
3. Appends the chart to the result as an `ImageContent` block with `mimeType: "image/svg+xml"` and base64-encoded `data`.

No external charting library is required.

### How to use it

```json
{
  "name": "research",
  "arguments": {
    "query": "Global EV market overview",
    "visualization": "auto"
  }
}
```

The `CallToolResult` will contain two content blocks: a `TextContent` with the written summary and an `ImageContent` with the chart.

### Metric extraction patterns

The extractor recognises patterns like:

| Text in summary | Extracted metric |
|---|---|
| `Market size: $4.5B` | `Market size ($B): 4.5` |
| `Growth rate: 12%` | `Growth rate (%): 12` |
| `Active users: 1.2M` | `Active users ($M): 1.2` |
| `Revenue: $800K` | `Revenue ($K): 800` |

Up to six metrics are extracted and displayed. If no numeric patterns are found the chart is omitted.

### Implementation

```python
from mcp_research_agent.visualization import extract_metrics, generate_bar_chart

metrics = extract_metrics(summary)        # dict[str, float]
chart_b64 = generate_bar_chart(metrics, title=query[:50])

content.append(
    types.ImageContent(
        type="image",
        data=chart_b64,
        mimeType="image/svg+xml",
    )
)
```

`generate_bar_chart` returns a base64-encoded UTF-8 SVG string. Clients that support `ImageContent` (e.g. Claude Desktop) will render the chart inline.

---

## Combining all three features

```json
{
  "name": "research",
  "arguments": {
    "query": "Renewable energy market growth 2024",
    "collaborative_planning": true,
    "visualization": "auto"
  }
}
```

With this call the agent will:

1. Draft a research plan and pause for your approval.
2. Query any configured remote MCP servers for relevant data.
3. Conduct the research and produce a written summary.
4. Return the summary together with a bar chart of the key metrics it found.

---

## Architecture overview

```
Client
  │
  │  call_tool("research", {...})
  ▼
StreamableHTTP transport
  │
  ▼
research-agent Server  (examples/research-agent/mcp_research_agent/server.py)
  │
  ├── ServerTaskContext.create_message()  ──▶  LLM (plan generation, research)
  ├── ServerTaskContext.elicit()          ──▶  Client UI (plan approval)
  ├── ClientSessionGroup.call_tool()      ──▶  Remote MCP servers (MCP support)
  └── generate_bar_chart()               ──▶  ImageContent (visualization)
```

## See also

- [Tasks and Elicitation](experimental/tasks.md) — the async task and elicitation primitives used by collaborative planning.
- [`ClientSessionGroup`](https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/client/session_group.py) — multi-server connection management used for MCP support.
- [`ImageContent`](https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/types.py) — the MCP type used to carry base64-encoded image data.
