# MCP Everything Server

A comprehensive example MCP server that demonstrates all features of the Model Context Protocol, including:

- Tools with progress reporting, logging, and elicitation
- Resource handling (static, dynamic, and templated)
- Prompts with arguments
- Completion support for resource templates and prompts
- Request context propagation
- Notifications and logging
- Sampling capabilities
- Structured output

## Usage

### Running the server

```bash
uv run mcp-server-everything
```

### Testing with MCP Inspector

```bash
mcp dev "uv run mcp-server-everything"
```

### Installing in Claude Desktop

```bash
mcp install "uv run mcp-server-everything" --name "Everything Server"
```

## Features

This server demonstrates:

- **Tools**: Echo, progress tracking, sampling, notifications, context access, elicitation
- **Resources**: Static resources, dynamic resources with parameters, resource templates
- **Prompts**: Simple and complex prompts with arguments
- **Completions**: Context-aware completion for prompts and resource templates
- **Notifications**: Progress updates, logging at different levels, resource/tool list changes
- **Elicitation**: Interactive user input during tool execution