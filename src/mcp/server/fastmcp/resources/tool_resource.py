"""Tool resource base class."""

import json
from typing import Any

from pydantic import AnyUrl, Field

from mcp.server.fastmcp.resources.base import Resource


class ToolResource(Resource):
    """Base class for tools that are also resources."""

    # Override mime_type default for tools
    mime_type: str = Field(
        default="application/json",
        description="MIME type of the resource content",
        pattern=r"^[a-zA-Z0-9]+/[a-zA-Z0-9\-+.]+$",
    )

    def __init__(self, **data: Any):
        # Auto-generate URI if not provided
        if "uri" not in data and "name" in data:
            data["uri"] = AnyUrl(f"tool://{data['name']}")
        super().__init__(**data)

    async def read(self) -> str | bytes:
        """Read the tool schema/documentation as JSON."""
        # This will be overridden by the Tool class
        return json.dumps(
            {
                "name": self.name,
                "title": self.title,
                "description": self.description,
                "uri": str(self.uri),
            }
        )
