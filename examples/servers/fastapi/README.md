# FastAPI app with MCP endpoint

A FastAPI application with a Streamable HTTP MCP endpoint mounted on `/mcp`.

The key difference when mounting on FastAPI vs Starlette is that you must manually call `mcp.session_manager.run()` in your FastAPI lifespan, as FastAPI doesn't automatically trigger the lifespan of mounted sub-applications.

## Usage

Start the server:

```bash
uv run uvicorn main:app --reload
```
