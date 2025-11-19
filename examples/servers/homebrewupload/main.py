import base64
import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator

import uvicorn
from markitdown import MarkItDown
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

# Initialize FastMCP server for MarkItDown (SSE)
# to different with markitdown official
mcp = FastMCP("markitdown_homebrew")

# Same with markitdown official
@mcp.tool()
async def convert_to_markdown(uri: str) -> str:
    """Convert a resource described by an http:, https:, file: or data: URI to markdown"""
    return MarkItDown(enable_plugins=check_plugins_enabled()).convert_uri(uri).markdown

# Same with markitdown official
def check_plugins_enabled() -> bool:
    return os.getenv("MARKITDOWN_ENABLE_PLUGINS", "false").strip().lower() in (
        "true",
        "1",
        "yes",
    )

# Same with markitdown official
def create_starlette_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    sse = SseServerTransport("/messages/")
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=True,
        stateless=True,
    )

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    async def handle_streamable_http(
        scope: Scope, receive: Receive, send: Send
    ) -> None:
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Context manager for session manager."""
        async with session_manager.run():
            print("Application started with StreamableHTTP session manager!")
            try:
                yield
            finally:
                print("Application shutting down...")

    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/mcp", app=handle_streamable_http),
            Mount("/messages/", app=sse.handle_post_message),
            # adding this as URL path
            Route(
                "/upload", endpoint=handle_file_upload, methods=["POST"]
            ),
        ],
        lifespan=lifespan,
    )

# added function for handle file upload
async def handle_file_upload(request: Request) -> JSONResponse:
    """
    handle file upload api
    """
    try:
        body = await request.json()
        filename = body.get("filename")
        file_content_base64 = body.get("file_content_base64")
        logging.info("process upload")
        logging.info(filename)
        logging.info(file_content_base64)
        if not filename:
            return JSONResponse({"error": "Filename is required"}, status_code=400)

        if not file_content_base64:
            return JSONResponse(
                {"error": "file_content_base64 is required"}, status_code=400
            )
        filename = os.path.basename(filename)
        file_path = os.path.join("/tmp/", filename)
        logging.info("start processing")
        try:
            file_data = base64.b64decode(file_content_base64)
        except Exception as e:
            logging.info(e)
            return JSONResponse(
                {"error": f"Invalid base64 data: {str(e)}"}, status_code=400
            )
        os.makedirs("/tmp", exist_ok=True)

        with open(file_path, "wb") as f:
            f.write(file_data)

        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            logging.info(
                f"File saved successfully: {file_path}, size: {file_size} bytes"
            )

            return JSONResponse(
                {
                    "status": "success",
                    "message": "File saved successfully",
                    "filename": filename,
                    "file_path": file_path,
                    "file_size": file_size,
                }
            )
        else:
            return JSONResponse({"error": "Failed to save file"}, status_code=500)

    except json.JSONDecodeError:
        logging.info(json.JSONDecodeError)
        return JSONResponse({"error": "Invalid JSON in request body"}, status_code=400)
    except Exception as e:
        logging.error(f"Error handling file upload: {str(e)}")
        return JSONResponse(
            {"error": f"Internal server error: {str(e)}"}, status_code=500
        )

# Main entry point
def main():
    mcp_server = mcp._mcp_server
    logging.info("start MCP server at 0.0.0.0:3001")
    starlette_app = create_starlette_app(mcp_server, debug=True)
    uvicorn.run(
            starlette_app,
            host="0.0.0.0",
            port=3001,
        )

if __name__ == "__main__":
    main()
