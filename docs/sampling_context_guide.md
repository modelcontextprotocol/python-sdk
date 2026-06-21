# Sampling Context Guide

This guide addresses common questions regarding the use of `RequestContext` and `includeContext` when making sampling requests to clients in the MCP Python SDK.

## Overview

Sampling allows an MCP server to request that the client use its available LLM to generate completions (via `create_message`). Two concepts that frequently cause confusion are the server's `RequestContext` and the `includeContext` sampling parameter.

Below are answers to common questions about using these components.

### 1. How can I access the LLM(s) available to the client directly, rather than making an explicit call?

**You cannot access the client's LLM directly.** 

The Model Context Protocol is designed so that the client securely controls access to its LLMs. Servers cannot bypass the protocol to access the LLM directly. You must make an explicit sampling request by calling `create_message` on the active session, allowing the client to execute the inference on your behalf.

### 2. How can I use `modelPreferences` to suggest that the client changes the choice of LLM based on priorities or name hints?

When sending a sampling request, you can provide a `ModelPreferences` object to help the client select the best available model for your use case.

```python
import mcp.types as types

# Define your preferences
preferences = types.ModelPreferences(
    hints=[types.ModelHint(name="claude-3-5-sonnet")],
    cost_priority=0.2,       # 0.0 to 1.0 (1.0 means cost is most important)
    speed_priority=0.8,      # 0.0 to 1.0 (1.0 means speed is most important)
    intelligence_priority=0.9 # 0.0 to 1.0 (1.0 means intelligence is most important)
)

# Pass the preferences to create_message
response = await ctx.session.create_message(
    messages=[
        types.SamplingMessage(
            role="user", 
            content=types.TextContent(type="text", text="Hello!")
        )
    ],
    max_tokens=1000,
    model_preferences=preferences
)
```

The client will prioritize `hints` (matching as a substring). If multiple models match or no hints are provided, the client can use the numeric priorities to weigh cost, speed, and intelligence.

### 3. How can I use the `RequestContext` to pass available context to the LLM for improved generation?

The `RequestContext` (typically `ServerRequestContext` or `Context` in the Python SDK) is a **server-side** object. It is *not* used to directly send context to the LLM.

Instead, the `RequestContext` gives your server handler access to the active connection's session. To pass context to the LLM, you should:
1. Retrieve the session from the context (`ctx.session`).
2. Include the context in your sampling prompt by adding it to the `messages` list in the `create_message` call.
3. Use the `include_context` argument to instruct the client to append its own context.

### 4. How can I use the `includeContext` attribute of `CreateMessageRequestParams` to filter what information is included in the context?

The `include_context` parameter dictates the **scope** of MCP-server context that the client should automatically attach to the sampling prompt, but it **cannot be used for granular filtering**.

You can pass one of three values:
- `"none"` (Default): No implicit context is added. The LLM only sees the messages you explicitly provided.
- `"thisServer"`: The client automatically includes recent interactions and context specifically related to your server (e.g., recent tool results or resources from this server).
- `"allServers"`: The client includes context from all servers connected to it.

*Note: You cannot use `includeContext` to say "include this specific resource but omit that specific tool result." It is a broad scope directive. If you need fine-grained control, set `include_context` to `"none"` and explicitly build the context within the `messages` array yourself.*
