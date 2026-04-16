"""Typed MCP request sugar over an `Outbound`.

`PeerMixin` defines the server-to-client request methods (sampling, elicitation,
roots, ping) once. Any class that satisfies `Outbound` (i.e. has `send_request`
and `notify`) can mix it in and get the typed methods for free — `Context`,
`Connection`, `Client`, or the bare `Peer` wrapper below.

The mixin does no capability gating: it builds the params, calls
``self.send_request(method, params)``, and parses the result into the typed
model. Gating (and `NoBackChannelError`) is the host's `send_request`'s job.
"""

from collections.abc import Mapping
from typing import Any, overload

from pydantic import BaseModel

from mcp.shared.dispatcher import CallOptions, Outbound
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateMessageResultWithTools,
    ElicitRequestedSchema,
    ElicitRequestFormParams,
    ElicitRequestURLParams,
    ElicitResult,
    IncludeContext,
    ListRootsResult,
    ModelPreferences,
    SamplingMessage,
    Tool,
    ToolChoice,
)

__all__ = ["Peer", "PeerMixin"]


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


class PeerMixin:
    """Typed server-to-client request methods.

    Each method constrains ``self`` to `Outbound` so the mixin can be applied
    to anything with ``send_request``/``notify`` — pyright checks the host
    class structurally at the call site.
    """

    @overload
    async def sample(
        self: Outbound,
        messages: list[SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: ModelPreferences | None = None,
        tools: None = None,
        tool_choice: ToolChoice | None = None,
        opts: CallOptions | None = None,
    ) -> CreateMessageResult: ...
    @overload
    async def sample(
        self: Outbound,
        messages: list[SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: ModelPreferences | None = None,
        tools: list[Tool],
        tool_choice: ToolChoice | None = None,
        opts: CallOptions | None = None,
    ) -> CreateMessageResultWithTools: ...
    async def sample(
        self: Outbound,
        messages: list[SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: ModelPreferences | None = None,
        tools: list[Tool] | None = None,
        tool_choice: ToolChoice | None = None,
        opts: CallOptions | None = None,
    ) -> CreateMessageResult | CreateMessageResultWithTools:
        """Send a ``sampling/createMessage`` request to the peer.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: The host's transport context has no
                back-channel for server-initiated requests.
        """
        params = CreateMessageRequestParams(
            messages=messages,
            system_prompt=system_prompt,
            include_context=include_context,
            temperature=temperature,
            max_tokens=max_tokens,
            stop_sequences=stop_sequences,
            metadata=metadata,
            model_preferences=model_preferences,
            tools=tools,
            tool_choice=tool_choice,
        )
        result = await self.send_request("sampling/createMessage", _dump(params), opts)
        if tools is not None:
            return CreateMessageResultWithTools.model_validate(result)
        return CreateMessageResult.model_validate(result)

    async def elicit_form(
        self: Outbound,
        message: str,
        requested_schema: ElicitRequestedSchema,
        opts: CallOptions | None = None,
    ) -> ElicitResult:
        """Send a form-mode ``elicitation/create`` request.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests.
        """
        params = ElicitRequestFormParams(message=message, requested_schema=requested_schema)
        result = await self.send_request("elicitation/create", _dump(params), opts)
        return ElicitResult.model_validate(result)

    async def elicit_url(
        self: Outbound,
        message: str,
        url: str,
        elicitation_id: str,
        opts: CallOptions | None = None,
    ) -> ElicitResult:
        """Send a URL-mode ``elicitation/create`` request.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests.
        """
        params = ElicitRequestURLParams(message=message, url=url, elicitation_id=elicitation_id)
        result = await self.send_request("elicitation/create", _dump(params), opts)
        return ElicitResult.model_validate(result)

    async def list_roots(self: Outbound, opts: CallOptions | None = None) -> ListRootsResult:
        """Send a ``roots/list`` request.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests.
        """
        result = await self.send_request("roots/list", None, opts)
        return ListRootsResult.model_validate(result)

    async def ping(self: Outbound, opts: CallOptions | None = None) -> None:
        """Send a ``ping`` request and ignore the result.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests.
        """
        await self.send_request("ping", None, opts)


class Peer(PeerMixin):
    """Standalone wrapper that gives any `Outbound` the `PeerMixin` sugar.

    `Context` and `Connection` mix `PeerMixin` in directly; use `Peer` when
    you have a bare dispatcher (or any `Outbound`) and want the typed methods
    without writing your own host class.
    """

    def __init__(self, outbound: Outbound) -> None:
        self._outbound = outbound

    async def send_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        return await self._outbound.send_request(method, params, opts)

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        await self._outbound.notify(method, params)
