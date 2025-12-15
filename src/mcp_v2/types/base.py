"""MCP Base Types - Core type definitions for MCP protocol."""

from typing import Annotated, Any, Final, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

LATEST_PROTOCOL_VERSION: Final[str] = "2025-11-25"

# MCP-specific type for progress tracking
ProgressToken = str | int


class MCPModel(BaseModel):
    """Base class for all MCP domain types. Allows extra fields for forward compatibility."""

    model_config = ConfigDict(extra="allow")


class RequestMeta(MCPModel):
    """Metadata for MCP requests."""

    progress_token: Annotated[ProgressToken | None, Field(alias="progressToken")] = None


class RequestParams(MCPModel):
    """Base class for MCP request parameters with _meta support."""

    meta: Annotated[RequestMeta | None, Field(alias="_meta")] = None


class Meta(MCPModel):
    """Base class for MCP meta information models."""


MetaT = TypeVar("MetaT", bound=Meta | dict[str, Any] | None)


class NotificationParams(MCPModel):
    """Base class for MCP notification parameters with _meta support."""

    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class Result(MCPModel, Generic[MetaT]):
    """Base class for MCP results with _meta support."""

    meta: Annotated[MetaT | None, Field(alias="_meta")] = None


# Method name literals for type-safe handler registration
RequestMethod = Literal[
    "initialize",
    "ping",
    "tools/call",
    "tools/list",
    "prompts/get",
    "prompts/list",
    "resources/read",
    "resources/list",
    "resources/templates/list",
    "completion/complete",
    "logging/setLevel",
]

# Notifications the client sends to server (server handles these)
ClientNotificationMethod = Literal[
    "notifications/initialized",
    "notifications/cancelled",
    "notifications/roots/list_changed",
]

# Notifications the server sends to client (for send_notification)
ServerNotificationMethod = Literal[
    "notifications/progress",
    "notifications/message",
    "notifications/resources/updated",
    "notifications/resources/list_changed",
    "notifications/tools/list_changed",
    "notifications/prompts/list_changed",
]
