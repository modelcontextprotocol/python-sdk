"""MCP Initialize Types - Types for the initialize handshake."""

from typing import Annotated, Literal

from pydantic import Field

from mcp_v2.types.base import Meta, RequestParams, Result
from mcp_v2.types.common import ClientCapabilities, Implementation, ServerCapabilities
from mcp_v2.types.json_rpc import NotificationBase, RequestBase


class InitializeRequestParams(RequestParams):
    """Parameters for the initialize request."""

    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    capabilities: ClientCapabilities
    client_info: Annotated[Implementation, Field(alias="clientInfo")]


class InitializeRequest(RequestBase[Literal["initialize"], InitializeRequestParams]):
    """Sent from client to server when first connecting."""

    method: Literal["initialize"] = "initialize"
    params: InitializeRequestParams


class InitializeResult(Result[Meta]):
    """Server's response to an initialize request."""

    protocol_version: Annotated[str, Field(alias="protocolVersion")]
    capabilities: ServerCapabilities
    server_info: Annotated[Implementation, Field(alias="serverInfo")]
    instructions: str | None = None


# PyCharm is dumb and doesn't understand `| None` and wants `Optional` instead, so ignoring.
# noinspection PyTypeChecker
class InitializedNotification(NotificationBase[Literal["notifications/initialized"], None]):
    """Sent from client to server after initialization is complete."""

    method: Literal["notifications/initialized"] = "notifications/initialized"
