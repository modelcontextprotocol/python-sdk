"""Regression test for issue #2376.

Image (and Audio) helpers returned from FastMCP tools must serialize to the
``ImageContent``/``AudioContent`` wire shape, including when stateless HTTP
mode is used by remote MCP clients.

The original report described
``Unable to serialize unknown type: mcp.server.fastmcp.utilities.types.Image``
from ``pydantic_core`` when the helper bypassed ``_convert_to_content`` and
was handed straight to Pydantic's JSON encoder. The fix gives ``Image`` and
``Audio`` a Pydantic core schema so any Pydantic-driven serializer produces
the right shape.
"""

import base64

import httpx
import pytest
from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Audio, Image


class _Holder(BaseModel):
    """Pydantic model used to round-trip helper instances through serialization."""

    model_config = {"arbitrary_types_allowed": True}

    image: Image | None = None
    audio: Audio | None = None


def test_image_serializes_as_image_content_via_pydantic() -> None:
    """Image must serialize as ImageContent when handed to a Pydantic encoder."""
    holder = _Holder(image=Image(data=b"hello", format="png"))
    dumped = holder.model_dump(mode="json", by_alias=True)["image"]
    assert dumped["type"] == "image"
    assert dumped["mimeType"] == "image/png"
    assert base64.b64decode(dumped["data"]) == b"hello"


def test_audio_serializes_as_audio_content_via_pydantic() -> None:
    """Audio must serialize as AudioContent when handed to a Pydantic encoder."""
    holder = _Holder(audio=Audio(data=b"world", format="wav"))
    dumped = holder.model_dump(mode="json", by_alias=True)["audio"]
    assert dumped["type"] == "audio"
    assert dumped["mimeType"] == "audio/wav"
    assert base64.b64decode(dumped["data"]) == b"world"


@pytest.mark.anyio
async def test_image_round_trips_through_stateless_http() -> None:
    """Returning Image from a FastMCP tool must produce ImageContent on the wire,
    end-to-end, in stateless HTTP mode with JSON responses (the configuration
    required by remote MCP clients that cannot maintain session state)."""
    mcp = FastMCP("test", host="0.0.0.0", stateless_http=True, json_response=True)

    @mcp.tool()
    def image_tool() -> Image:
        return Image(data=b"hello", format="png")

    app = mcp.streamable_http_app()
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1",
            timeout=10.0,
        ) as client:
            initialize = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"},
                    },
                },
                headers=headers,
            )
            assert initialize.status_code == 200

            call = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "image_tool", "arguments": {}},
                },
                headers=headers,
            )

    assert call.status_code == 200
    body = call.json()
    content = body["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "image"
    assert content[0]["mimeType"] == "image/png"
    assert base64.b64decode(content[0]["data"]) == b"hello"
    assert body["result"]["isError"] is False
