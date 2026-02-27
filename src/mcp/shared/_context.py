"""Request context for MCP handlers."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic

from typing_extensions import TypeVar

if TYPE_CHECKING:
    from mcp.shared.session import AbstractBaseSession

from mcp.types import RequestId, RequestParamsMeta

SessionT_co = TypeVar("SessionT_co", bound="AbstractBaseSession[Any, Any]", covariant=True)


@dataclass(kw_only=True)
class RequestContext(Generic[SessionT_co]):
    """Common context for handling incoming requests.

    For request handlers, request_id is always populated.
    For notification handlers, request_id is None.
    """

    session: SessionT_co
    request_id: RequestId | None = None
    meta: RequestParamsMeta | None = None
