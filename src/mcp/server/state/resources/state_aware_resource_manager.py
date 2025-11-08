from __future__ import annotations

from typing import Iterable

from pydantic import AnyUrl

from mcp.server.fastmcp.exceptions import ResourceError
from mcp.server.fastmcp.resources import Resource, ResourceManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.state.machine.state_machine import InputSymbol, StateMachine
from mcp.server.state.types import FastMCPContext, ResourceResultType
from mcp.server.state.transaction.async_transaction_scope import AsyncTransactionScope
from mcp.server.state.transaction.manager import TransactionManager

logger = get_logger(__name__)


class StateAwareResourceManager:
    """State-aware **facade** over ``ResourceManager``.

    Wraps a ``StateMachine`` and delegates to the native manager while
    constraining discovery and reads by the machine's *current state*.

    Facade model:
    - Discovery: use ``state_machine.available_symbols("resource")`` to list allowed resource **URIs**.
    - Outer: `AsyncTransactionScope` prepares (state, "resource", uri, outcome). On PREPARE failure → stop.
    - Inner: `state_machine.step(success_symbol, error_symbol, ctx=...)` drives SUCCESS/ERROR edges.
      Effects triggered by edges are fire-and-forget and must not affect state changes.
    """

    def __init__(
        self,
        state_machine: StateMachine,
        resource_manager: ResourceManager,
        tx_manager: TransactionManager,
    ):
        self._resource_manager = resource_manager
        self._state_machine = state_machine
        self._tx_manager = tx_manager

    async def list_resources(self) -> list[Resource]:
        """Return resources allowed in the **current state** (by URI via ``available_symbols("resource")``).

        Missing registrations are logged as warnings (soft), not raised.
        """
        allowed_uris = self._state_machine.available_symbols("resource")  # Set[str]
        available: list[Resource] = []
        for uri in allowed_uris:
            res = await self._resource_manager.get_resource(uri)
            if res is not None:
                available.append(res)
            else:
                logger.warning(
                    "Resource '%s' expected in state '%s' but not registered.",
                    uri,
                    self._state_machine.current_state,
                )
        return available

    async def read_resource(
        self,
        uri: str | AnyUrl,
        ctx: FastMCPContext,
    ) -> Iterable[ReadResourceContents]:
        """Read the resource in the **current state** with SUCCESS/ERROR step semantics.

        Steps:
        1) Pre-validate: URI must be in ``available_symbols('resource')`` and registered.
        2) Outer: `AsyncTransactionScope` (prepare/commit/abort) scoped to (state, "resource", uri).
        3) Inner: `state_machine.step(...)` emits SUCCESS/ERROR edges around the read.
        4) Perform the read and wrap the payload as ``ReadResourceContents``.
        """
        allowed = self._state_machine.available_symbols("resource")
        uri_str = str(uri)
        if uri_str not in allowed:
            raise ResourceError(
                f"Resource '{uri}' is not allowed in state '{self._state_machine.current_state(ctx)}'. "
                f"Try `list/resources` first to inspect availability."
            )

        resource = await self._resource_manager.get_resource(uri_str)
        if not resource:
            raise ResourceError(f"Unknown resource: {uri}")

        current_state = self._state_machine.current_state(ctx)

        # OUTER: transactions
        async with AsyncTransactionScope(
            tx_manager=self._tx_manager,
            state=current_state,
            kind="resource",
            name=uri_str,
            ctx=ctx,
        ):
            # INNER: state step scope
            async with self._state_machine.step(
                success_symbol=InputSymbol.for_resource(uri_str, ResourceResultType.SUCCESS),
                error_symbol=InputSymbol.for_resource(uri_str, ResourceResultType.ERROR),
                ctx=ctx,
            ):
                content = await resource.read()
                return [ReadResourceContents(content=content, mime_type=resource.mime_type)]
