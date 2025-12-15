"""Minimum amount of base models to represent the types from JSON-RPC used by MCP."""

from typing import Annotated, Any, Final, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

JSONRPC_VERSION: Final[str] = "2.0"

PARSE_ERROR: Final[int] = -32700
INVALID_REQUEST: Final[int] = -32600
METHOD_NOT_FOUND: Final[int] = -32601
INVALID_PARAMS: Final[int] = -32602
INTERNAL_ERROR: Final[int] = -32603

RequestId = Annotated[int, Field(strict=True)] | str


class JSONRPCBase(BaseModel):
    """Base class for all JSON-RPC messages."""

    model_config = ConfigDict(extra="allow")

    jsonrpc: Literal["2.0"] = JSONRPC_VERSION


MethodT = TypeVar("MethodT", bound=str)
ParamsT = TypeVar("ParamsT", bound=BaseModel | dict[str, Any] | None)


class RequestBase(JSONRPCBase, Generic[MethodT, ParamsT]):
    """A request that expects a response."""

    id: RequestId
    method: MethodT
    params: ParamsT


# PyCharm is dumb and doesn't understand `| None` and wants `Optional` instead, so ignoring.
# noinspection PyTypeChecker
class JSONRPCRequest(RequestBase[str, dict[str, Any] | None]):
    """A request that expects a response."""

    params: dict[str, Any] | None = None


class NotificationBase(JSONRPCBase, Generic[MethodT, ParamsT]):
    """A notification which does not expect a response."""

    method: MethodT
    params: ParamsT


# PyCharm is dumb and doesn't understand `| None` and wants `Optional` instead, so ignoring.
# noinspection PyTypeChecker
class JSONRPCNotification(NotificationBase[str, dict[str, Any] | None]):
    """A notification which does not expect a response."""

    params: dict[str, Any] | None = None


class ErrorData(BaseModel):
    """Error information in a JSON-RPC error response."""

    model_config = ConfigDict(extra="allow")

    code: int
    message: str
    data: Any | None = None


ResultT = TypeVar("ResultT", bound=BaseModel | dict[str, Any])


class ResultResponseBase(JSONRPCBase, Generic[ResultT]):
    """A successful (non-error) response to a request."""

    id: RequestId
    result: ResultT


class JSONRPCResultResponse(ResultResponseBase[dict[str, Any]]):
    """A successful (non-error) response to a request."""


class JSONRPCErrorResponse(JSONRPCBase):
    """A response to a request that indicates an error occurred."""

    id: RequestId | None = None
    error: ErrorData


JSONRPCResponse = JSONRPCResultResponse | JSONRPCErrorResponse
JSONRPCMessage = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse

JSONRPCMessageAdapter: TypeAdapter[JSONRPCMessage] = TypeAdapter(JSONRPCMessage)
