"""
Example showing how to return ResourceContents objects directly from
low-level server resources.

The main benefit is the ability to include metadata (_meta field) with
your resources, providing additional context about the resource content
such as timestamps, versions, authorship, or any domain-specific metadata.
"""

import asyncio
from collections.abc import Iterable

from pydantic import AnyUrl

import mcp.server.stdio as stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.lowlevel.server import ReadResourceContents

# Create a server instance
server = Server(
    name="LowLevel ResourceContents Example",
    version="1.0.0",
)


# Example 1: Return TextResourceContents directly
@server.read_resource()
async def read_resource(uri: AnyUrl) -> Iterable[types.TextResourceContents | types.BlobResourceContents]:
    """Handle resource reading with direct ResourceContents return."""
    uri_str = str(uri)

    if uri_str == "text://readme":
        # Return TextResourceContents with document metadata
        return [
            types.TextResourceContents(
                uri=uri,
                text="# README\n\nThis is a sample readme file.",
                mimeType="text/markdown",
                _meta={
                    "title": "Project README",
                    "author": "Development Team",
                    "lastModified": "2024-01-15T10:00:00Z",
                    "version": "2.1.0",
                    "language": "en",
                    "license": "MIT",
                },
            )
        ]

    elif uri_str == "data://config.json":
        # Return JSON data with schema and validation metadata
        return [
            types.TextResourceContents(
                uri=uri,
                text='{\n  "version": "1.0.0",\n  "debug": false\n}',
                mimeType="application/json",
                _meta={
                    "schema": "https://example.com/schemas/config/v1.0",
                    "validated": True,
                    "environment": "production",
                    "lastValidated": "2024-01-15T14:00:00Z",
                    "checksum": "sha256:abc123...",
                },
            )
        ]

    elif uri_str == "image://icon.png":
        # Return binary data with comprehensive image metadata
        import base64

        # This is a 1x1 transparent PNG
        png_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        )
        return [
            types.BlobResourceContents(
                uri=uri,
                blob=base64.b64encode(png_data).decode(),
                mimeType="image/png",
                _meta={
                    "width": 1,
                    "height": 1,
                    "bitDepth": 8,
                    "colorType": 6,  # RGBA
                    "compression": 0,
                    "filter": 0,
                    "interlace": 0,
                    "fileSize": len(png_data),
                    "hasAlpha": True,
                    "generated": "2024-01-15T12:00:00Z",
                    "generator": "Example MCP Server",
                },
            )
        ]

    elif uri_str == "multi://content":
        # Return multiple ResourceContents objects with part metadata
        return [
            types.TextResourceContents(
                uri=uri,
                text="Part 1: Introduction",
                mimeType="text/plain",
                _meta={
                    "part": 1,
                    "title": "Introduction",
                    "order": 1,
                    "required": True,
                },
            ),
            types.TextResourceContents(
                uri=uri,
                text="## Part 2: Main Content\n\nThis is the main section.",
                mimeType="text/markdown",
                _meta={
                    "part": 2,
                    "title": "Main Content",
                    "order": 2,
                    "wordCount": 8,
                    "headingLevel": 2,
                },
            ),
            types.BlobResourceContents(
                uri=uri,
                blob="UGFydCAzOiBCaW5hcnkgRGF0YQ==",  # "Part 3: Binary Data" in base64
                mimeType="application/octet-stream",
                _meta={
                    "part": 3,
                    "title": "Binary Attachment",
                    "order": 3,
                    "encoding": "base64",
                    "originalSize": 19,
                },
            ),
        ]

    elif uri_str.startswith("code://"):
        # Extract language from URI for syntax highlighting
        language = uri_str.split("://")[1].split("/")[0]
        code_samples = {
            "python": ('def hello():\n    print("Hello, World!")', "text/x-python"),
            "javascript": ('console.log("Hello, World!");', "text/javascript"),
            "html": ("<h1>Hello, World!</h1>", "text/html"),
        }

        if language in code_samples:
            code, mime_type = code_samples[language]
            return [
                types.TextResourceContents(
                    uri=uri,
                    text=code,
                    mimeType=mime_type,
                    _meta={
                        "language": language,
                        "syntaxHighlighting": True,
                        "lineNumbers": True,
                        "executable": language in ["python", "javascript"],
                        "documentation": f"https://docs.example.com/languages/{language}",
                    },
                )
            ]

    # Default case - resource not found
    return [
        types.TextResourceContents(
            uri=uri,
            text=f"Resource not found: {uri}",
            mimeType="text/plain",
        )
    ]


# List available resources
@server.list_resources()
async def list_resources() -> list[types.Resource]:
    """List all available resources."""
    return [
        types.Resource(
            uri=AnyUrl("text://readme"),
            name="README",
            title="README file",
            description="A sample readme in markdown format",
            mimeType="text/markdown",
        ),
        types.Resource(
            uri=AnyUrl("data://config.json"),
            name="config",
            title="Configuration",
            description="Application configuration in JSON format",
            mimeType="application/json",
        ),
        types.Resource(
            uri=AnyUrl("image://icon.png"),
            name="icon",
            title="Application Icon",
            description="A sample PNG icon",
            mimeType="image/png",
        ),
        types.Resource(
            uri=AnyUrl("multi://content"),
            name="multi-part",
            title="Multi-part Content",
            description="A resource that returns multiple content items",
            mimeType="multipart/mixed",
        ),
        types.Resource(
            uri=AnyUrl("code://python/example"),
            name="python-code",
            title="Python Code Example",
            description="Sample Python code with proper MIME type",
            mimeType="text/x-python",
        ),
    ]


# Also demonstrate with ReadResourceContents (old style) mixed in
@server.list_resources()
async def list_legacy_resources() -> list[types.Resource]:
    """List resources that use the legacy ReadResourceContents approach."""
    return [
        types.Resource(
            uri=AnyUrl("legacy://text"),
            name="legacy-text",
            title="Legacy Text Resource",
            description="Uses ReadResourceContents wrapper",
            mimeType="text/plain",
        ),
    ]


# Mix old and new styles to show compatibility
@server.read_resource()
async def read_legacy_resource(
    uri: AnyUrl,
) -> Iterable[ReadResourceContents | types.TextResourceContents | types.BlobResourceContents]:
    """Handle legacy resources alongside new ResourceContents."""
    uri_str = str(uri)

    if uri_str == "legacy://text":
        # Old style - return ReadResourceContents
        return [
            ReadResourceContents(
                content="This uses the legacy ReadResourceContents wrapper",
                mime_type="text/plain",
            )
        ]

    # For other resources, return a simple not found message
    return [
        types.TextResourceContents(
            uri=uri,
            text=f"Resource not found: {uri}",
            mimeType="text/plain",
        )
    ]


async def main():
    """Run the server using stdio transport."""
    async with stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )


if __name__ == "__main__":
    # Run with: python resource_contents_direct.py
    asyncio.run(main())
