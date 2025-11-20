# Simple Sampling Client Example (MCP)

This example demonstrates how to use the sampling capability of the MCP SDK with an OpenAI-compatible client. It shows how to:

- Connect to an MCP server
- Fetch available tools
- Use OpenAI's API for chat completions
- Call MCP tools from the client

## Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) for dependency management
- An OpenAI API key (set in a `.env` file or as an environment variable)

## Setup

1. Install dependencies:

 ```sh
 cd examples/clients/simple-sampling-client/
 uv sync
 ```

2. Set environment variables in a `.env` file. A sample `.env` file is provided as `.env.example`.

3. Start the MCP server in a separate terminal:

 ```sh
 cd examples/snippets/servers/
 uv run server sampling streamable-http
 ```

4. Run the sampling client in previous terminal:

 ```sh
 uv run mcp-simple-sampling-client
 ```

## Usage

You will be prompted to enter a message. Type your message and press Enter. The assistant will respond using the sampling capability and may call MCP tools as needed.

Type `exit` or `quit` to stop the client.

## Code Overview

For more details, see the source code in `mcp_simple_sampling_client/main.py`.
