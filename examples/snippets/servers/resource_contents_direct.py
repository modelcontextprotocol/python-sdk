"""
Example showing how to return ResourceContents objects directly from resources.

The main benefit of returning ResourceContents directly is the ability to include
metadata through the _meta field. This allows
you to attach additional context to your resources such as:

- Timestamps (created, modified, expires)
- Version information
- Author/ownership details
- File system metadata (permissions, size)
- Image metadata (dimensions, color space)
- Document metadata (word count, language)
- Validation status and schemas
- Any domain-specific metadata

This metadata helps clients better understand and work with the resource content.
"""

import base64

from pydantic import AnyUrl

from mcp.server.fastmcp import FastMCP
from mcp.types import BlobResourceContents, TextResourceContents

mcp = FastMCP(name="Direct ResourceContents Example")


# Example 1: Return TextResourceContents with metadata
@mcp.resource("document://report")
def get_report() -> TextResourceContents:
    """Return a report with metadata about creation time and author."""
    return TextResourceContents(
        uri=AnyUrl("document://report"),
        text="# Monthly Report\n\nThis is the monthly report content.",
        mimeType="text/markdown",
        # The main benefit: adding metadata to the resource
        _meta={
            "created": "2024-01-15T10:30:00Z",
            "author": "Analytics Team",
            "version": "1.2.0",
            "tags": ["monthly", "finance", "q1-2024"],
            "confidentiality": "internal",
        },
    )


# Example 2: Return BlobResourceContents with image metadata
@mcp.resource("image://logo")
def get_logo() -> BlobResourceContents:
    """Return a logo image with metadata about dimensions and format."""
    # In a real app, you might read this from a file
    image_bytes = b"\x89PNG\r\n\x1a\n..."  # PNG header

    return BlobResourceContents(
        uri=AnyUrl("image://logo"),
        blob=base64.b64encode(image_bytes).decode(),
        mimeType="image/png",
        # Image-specific metadata
        _meta={
            "width": 512,
            "height": 512,
            "format": "PNG",
            "colorSpace": "sRGB",
            "hasAlpha": True,
            "fileSize": 24576,
            "lastModified": "2024-01-10T08:00:00Z",
        },
    )


# Example 3: Dynamic resource with real-time metadata
@mcp.resource("data://metrics/{metric_type}")
async def get_metrics(metric_type: str) -> TextResourceContents:
    """Return metrics data with metadata about collection time and source."""
    import datetime
    from datetime import timezone

    # Simulate collecting metrics
    metrics = {"cpu": 45.2, "memory": 78.5, "disk": 62.1}
    timestamp = datetime.datetime.now(timezone.utc).isoformat()

    if metric_type == "json":
        import json

        return TextResourceContents(
            uri=AnyUrl(f"data://metrics/{metric_type}"),
            text=json.dumps(metrics, indent=2),
            mimeType="application/json",
            _meta={
                "timestamp": timestamp,
                "source": "system_monitor",
                "interval": "5s",
                "aggregation": "average",
                "host": "prod-server-01",
            },
        )
    elif metric_type == "csv":
        csv_text = "metric,value\n" + "\n".join(f"{k},{v}" for k, v in metrics.items())
        return TextResourceContents(
            uri=AnyUrl(f"data://metrics/{metric_type}"),
            text=csv_text,
            mimeType="text/csv",
            _meta={
                "timestamp": timestamp,
                "columns": ["metric", "value"],
                "row_count": len(metrics),
            },
        )
    else:
        text = "\n".join(f"{k.upper()}: {v}%" for k, v in metrics.items())
        return TextResourceContents(
            uri=AnyUrl(f"data://metrics/{metric_type}"),
            text=text,
            mimeType="text/plain",
            _meta={
                "timestamp": timestamp,
                "format": "human-readable",
            },
        )


# Example 4: Configuration resource with version metadata
@mcp.resource("config://app")
def get_config() -> TextResourceContents:
    """Return application config with version and environment metadata."""
    import json

    config = {
        "version": "1.0.0",
        "features": {
            "dark_mode": True,
            "auto_save": False,
            "language": "en",
        },
        "limits": {
            "max_file_size": 10485760,  # 10MB
            "max_connections": 100,
        },
    }

    return TextResourceContents(
        uri=AnyUrl("config://app"),
        text=json.dumps(config, indent=2),
        mimeType="application/json",
        _meta={
            "version": "1.0.0",
            "lastUpdated": "2024-01-15T14:30:00Z",
            "environment": "production",
            "schema": "https://example.com/schemas/config/v1.0",
            "editable": False,
        },
    )


# Example 5: Database query result with execution metadata
@mcp.resource("db://query/users")
async def get_users() -> TextResourceContents:
    """Return query results with execution time and row count."""
    import json
    import time

    # Simulate database query
    start_time = time.time()
    users = [
        {"id": 1, "name": "Alice", "role": "admin"},
        {"id": 2, "name": "Bob", "role": "user"},
        {"id": 3, "name": "Charlie", "role": "user"},
    ]
    execution_time = time.time() - start_time

    return TextResourceContents(
        uri=AnyUrl("db://query/users"),
        text=json.dumps(users, indent=2),
        mimeType="application/json",
        _meta={
            "query": "SELECT * FROM users",
            "executionTime": f"{execution_time:.3f}s",
            "rowCount": len(users),
            "database": "main",
            "cached": False,
            "timestamp": "2024-01-15T16:00:00Z",
        },
    )


if __name__ == "__main__":
    # Run with: python resource_contents_direct.py
    mcp.run()
