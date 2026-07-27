"""Typed MCP request sugar over an `Outbound`.

`ClientPeer` wraps any `Outbound` (anything with `send_raw_request` and
`notify`) and exposes the server-to-client request methods (sampling,
elicitation, roots, ping) as typed methods.

`ClientPeer` does no capability gating: it builds the params, calls
`send_raw_request(method, params)`, and parses the result into the typed
model. Gating (and `NoBackChannelError`) is the wrapped `Outbound`'s job.
"""

from collections.abc import Mapping
from typing import Any, cast, overload

from mcp_types import (
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
    RequestParams,
    RequestParamsMeta,
    SamplingMessage,
    Tool,
    ToolChoice,
)
from pydantic import BaseModel
from typing_extensions import deprecated

from mcp.shared.dispatcher import CallOptions, Outbound
from mcp.shared.exceptions import MCPDeprecationWarning

__all__ = ["ClientPeer", "Meta"]

Meta = dict[str, Any]
"""Type alias for the `_meta` field carried on request/notification params."""


def dump_params(model: BaseModel | None, meta: Meta | None = None) -> dict[str, Any] | None:
    """Serialize a params model to a wire dict, merging `meta` into `_meta`.

    Shared by `ClientPeer` and `Connection` so every typed convenience method
    gets the same `_meta` handling. `meta` keys take precedence over any
    `_meta` already present on the model.

    `meta` is serialized through `RequestParams` so Python field names emit
    their wire aliases: an inbound `ctx.meta` carries `progress_token` (the
    key `_extract_meta` validation produces), and forwarding it outbound via
    `meta=ctx.meta` must put `progressToken` back on the wire. Keys not
    declared on `RequestParamsMeta` pass through unchanged.
    """
    out = model.model_dump(by_alias=True, mode="json", exclude_none=True) if model is not None else None
    if meta:
        wire_meta = RequestParams(_meta=cast(RequestParamsMeta, meta)).model_dump(by_alias=True, mode="json")["_meta"]
        out = dict(out or {})
        out["_meta"] = {**out.get("_meta", {}), **wire_meta}
    return out


class ClientPeer:
    """Typed server-to-client request methods over a wrapped `Outbound`.

    Use this when you have a bare dispatcher (or any `Outbound`) and want the
    typed methods (`sample`, `elicit_form`, `elicit_url`, `list_roots`,
    `ping`) without writing your own host class.
    """

    def __init__(self, outbound: Outbound) -> None:
        self._outbound = outbound

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        return await self._outbound.send_raw_request(method, params, opts)

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        await self._outbound.notify(method, params, opts)

    @overload
    @deprecated("The sampling capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def sample(
        self,
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
        tool_choice: None = None,
        meta: Meta | None = None,
        opts: CallOptions | None = None,
    ) -> CreateMessageResult: ...
    @overload
    @deprecated("The sampling capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def sample(
        self,
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
        meta: Meta | None = None,
        opts: CallOptions | None = None,
    ) -> CreateMessageResultWithTools: ...
    @overload
    @deprecated("The sampling capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def sample(
        self,
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
        tool_choice: ToolChoice,
        meta: Meta | None = None,
        opts: CallOptions | None = None,
    ) -> CreateMessageResultWithTools: ...
    @deprecated("The sampling capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def sample(
        self,
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
        meta: Meta | None = None,
        opts: CallOptions | None = None,
    ) -> CreateMessageResult | CreateMessageResultWithTools:
        """Send a `sampling/createMessage` request to the peer.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests.
            pydantic.ValidationError: The peer's result does not match the expected result type.
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
        result = await self.send_raw_request("sampling/createMessage", dump_params(params, meta), opts)
        if tools is not None or tool_choice is not None:
            return CreateMessageResultWithTools.model_validate(result, by_name=False)
        return CreateMessageResult.model_validate(result, by_name=False)

    async def elicit_form(
        self,
        message: str,
        requested_schema: ElicitRequestedSchema,
        *,
        meta: Meta | None = None,
        opts: CallOptions | None = None,
    ) -> ElicitResult:
        """Send a form-mode `elicitation/create` request.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests.
            pydantic.ValidationError: The peer's result does not match the expected result type.
        """
        params = ElicitRequestFormParams(message=message, requested_schema=requested_schema)
        result = await self.send_raw_request("elicitation/create", dump_params(params, meta), opts)
        return ElicitResult.model_validate(result, by_name=False)

    async def elicit_url(
        self,
        message: str,
        url: str,
        elicitation_id: str,
        *,
        meta: Meta | None = None,
        opts: CallOptions | None = None,
    ) -> ElicitResult:
        """Send a URL-mode `elicitation/create` request.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests.
            pydantic.ValidationError: The peer's result does not match the expected result type.
        """
        params = ElicitRequestURLParams(message=message, url=url, elicitation_id=elicitation_id)
        result = await self.send_raw_request("elicitation/create", dump_params(params, meta), opts)
        return ElicitResult.model_validate(result, by_name=False)

    @deprecated("The roots capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def list_roots(self, *, meta: Meta | None = None, opts: CallOptions | None = None) -> ListRootsResult:
        """Send a `roots/list` request.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests.
            pydantic.ValidationError: The peer's result does not match the expected result type.
        """
        result = await self.send_raw_request("roots/list", dump_params(None, meta), opts)
        return ListRootsResult.model_validate(result, by_name=False)

    async def ping(self, *, meta: Meta | None = None, opts: CallOptions | None = None) -> None:
        """Send a `ping` request and ignore the result.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests.
        """
        await self.send_raw_request("ping", dump_params(None, meta), opts)
