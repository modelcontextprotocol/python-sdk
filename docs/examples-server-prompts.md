# Server prompts examples

Prompts are reusable templates that help structure LLM interactions. They provide a way to define consistent interaction patterns that users can invoke.

## Basic prompts

Simple prompt templates for common scenarios:

```python
--8<-- "examples/snippets/servers/basic_prompt.py"
```

This example demonstrates:

- Simple string prompts (`review_code`)
- Multi-message prompt conversations (`debug_error`)
- Using different message types (User and Assistant messages)
- Prompt titles for better user experience

## Simple prompt server

A complete server focused on prompt management:

```python
--8<-- "examples/servers/simple-prompt/mcp_simple_prompt/server.py"
```

This low-level server example shows:

- Prompt listing and retrieval
- Argument handling and validation
- Dynamic prompt generation based on parameters
- Production-ready prompt patterns using the low-level API

Prompts are user-controlled primitives that help create consistent, reusable interaction patterns. They're particularly useful for:

- Code review templates
- Debugging assistance workflows
- Content generation patterns
- Structured analysis requests

Unlike tools (which are model-controlled) and resources (which are application-controlled), prompts are invoked directly by users to initiate specific types of interactions with the LLM.