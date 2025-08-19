# Server tools examples

Tools are functions that LLMs can call to perform actions or computations. This section demonstrates various tool patterns and capabilities.

## Basic tools

Simple tools that perform computations and return results:

```python
--8<-- "examples/snippets/servers/basic_tool.py"
```

## Tools with context and progress reporting

Tools can access MCP context for logging, progress reporting, and other capabilities:

```python
--8<-- "examples/snippets/servers/tool_progress.py"
```

This example shows:

- Using the `Context` parameter for MCP capabilities
- Progress reporting during long-running operations
- Structured logging at different levels
- Async tool functions

## Complex input handling

Tools can handle complex data structures and validation:

```python
--8<-- "examples/fastmcp/complex_inputs.py"
```

## Parameter descriptions

Tools with detailed parameter descriptions and validation:

```python
--8<-- "examples/fastmcp/parameter_descriptions.py"
```

## Unicode and internationalization

Handling Unicode and international text in tools:

```python
--8<-- "examples/fastmcp/unicode_example.py"
```

## Desktop integration

Tools that interact with the desktop environment:

```python
--8<-- "examples/fastmcp/desktop.py"
```

## Screenshot tools

Tools for taking and processing screenshots:

```python
--8<-- "examples/fastmcp/screenshot.py"
```

## Text processing tools

Tools for text manipulation and processing:

```python
--8<-- "examples/fastmcp/text_me.py"
```

All tool examples demonstrate different aspects of MCP tool development, from basic computation to complex system interactions.