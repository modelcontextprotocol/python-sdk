"""Companion examples for src/mcp/shared/response_router.py docstrings."""

from __future__ import annotations

from typing import Any

from mcp.shared.experimental.tasks.resolver import Resolver
from mcp.shared.response_router import ResponseRouter
from mcp.types import RequestId


def ResponseRouter_usage() -> None:
    # region ResponseRouter_usage
    class TaskResultHandler(ResponseRouter):
        _pending_requests: dict[RequestId, Resolver[dict[str, Any]]]

        def route_response(self, request_id: Any, response: Any) -> bool:
            resolver = self._pending_requests.pop(request_id, None)
            if resolver:
                resolver.set_result(response)
                return True
            return False

    # endregion ResponseRouter_usage
