# Dynamic MCP Agent

This project implements an MCP server that acts as a bridge between a Main LLM and a set of dynamically loaded tools, orchestrated by an internal, custom LLM.

## Setup

1.  Clone the repository.
2.  Create a virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`
    ```
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Rename `.env.example` to `.env` and fill in your API keys and endpoints:
    ```bash
    cp dynamic_mcp_agent/.env.example dynamic_mcp_agent/.env
    # Now edit dynamic_mcp_agent/.env
    ```
5. Populate `dynamic_mcp_agent/tools.json` with your desired tools.

## Running Local Tests

The `app.py` script includes a set of local integration tests that verify the core logic of the agent and tool execution. These tests run by default when executing `app.py`. To run these tests:

```bash
python -m dynamic_mcp_agent.app
```

This will execute the tests defined in the `run_local_integration_tests` function within `app.py`. The output will show the queries being processed, the mock LLM's behavior, tool calls, and final agent responses.

## Running the Server (stdio)

To run the actual MCP server using STDIN/STDOUT for communication (e.g., for use with `mcp chat stdio:/`):

1.  Modify the `if __name__ == "__main__":` block in `dynamic_mcp_agent/app.py`.
2.  Comment out the line:
    ```python
    # asyncio.run(run_local_integration_tests(mcp_server))
    ```
3.  Uncomment the following lines (or ensure they are present and uncommented):
    ```python
    # print("\nStarting Dynamic MCP Agent server with STDIN/STDOUT transport...")
    # print("Run 'mcp chat stdio:/' in another terminal to connect.")
    # try:
    #     mcp_server.run(transport="stdio")
    # # ... (error handling code should also be uncommented) ...
    ```
4.  Then run the application:
    ```bash
    python -m dynamic_mcp_agent.app
    ```
    You can then connect to it using an MCP client like `mcp chat stdio:/`.

(Instructions for running with HTTP transports like SSE or StreamableHTTP using Uvicorn are also available as commented-out sections within `dynamic_mcp_agent/app.py`.)
```
