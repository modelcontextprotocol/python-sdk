from __future__ import annotations

from typing import Iterable

from pydantic import AnyUrl

from mcp.server.fastmcp.exceptions import ResourceError
from mcp.server.fastmcp.resources import Resource, ResourceManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.state.types import FastMCPContext
from mcp.server.state.machine.state_machine import (
    InputSymbol,
    ResourceResultType,
    StateMachine,
)
from mcp.server.state.transaction.async_transaction_scope import AsyncTransactionScope
from mcp.server.state.transaction.manager import TransactionManager

logger = get_logger(f"{__name__}.StateAwareResourceManager")


class StateAwareResourceManager:
    """State-aware facade over ``ResourceManager`` (composition).

    Wraps a ``StateMachine`` (global or session-scoped) and delegates to the native
    ``ResourceManager``; stays fully compatible with registrations and APIs.

    Model:
    - Access is gated by the machine's *current state*.
    - The actual read is wrapped by the machine’s **AsyncTransitionScope**.
    - Transactions are handled by a separate **AsyncTransactionScope** nested inside; it
      prepares/commits/aborts for (state, "resource", uri). Any transaction failure bubbles up,
      causing the transition scope to emit the ERROR transition.

    Note:
      Resource templates (``list_resource_templates``) are still handled by **FastMCP**.
    """

    def __init__(
            self, 
            state_machine: StateMachine, 
            resource_manager: ResourceManager,
            tx_manager: TransactionManager
        ):
        self._resource_manager = resource_manager
        self._state_machine = state_machine
        self._tx_manager = tx_manager

    async def list_resources(self) -> list[Resource]:
        """Return resources allowed in the **current_state**.

        Missing registrations are logged as warnings (soft), not raised.
        """
        resource_uris = self._state_machine.get_available_inputs().get("resources", set())

        available: list[Resource] = []
        for uri in resource_uris:
            resource = await self._resource_manager.get_resource(uri)
            if resource is not None:
                available.append(resource)
            else:
                logger.warning(
                    "Resource '%s' expected in state '%s' but not registered.",
                    uri,
                    self._state_machine.current_state,
                )
        return available

    async def read_resource(self, uri: str | AnyUrl, ctx: FastMCPContext) -> Iterable[ReadResourceContents]:
        """
        Read the resource in the **current state**.

        Steps
        -----
        1) **Pre-validate**: resource must be allowed by the state machine and registered.
        2) **Wrap with transitions**: `AsyncTransitionScope` emits SUCCESS/ERROR.
        3) **Wrap with transactions**: `AsyncTransactionScope` prepares/commits/aborts for
           (state, "resource", uri). Any transaction error propagates, causing ERROR transition.

        Returns:
            Iterable with a single `ReadResourceContents` entry (content + mime type).
        """
        allowed = self._state_machine.get_available_inputs().get("resources", set())
        uri_str = str(uri)
        if uri_str not in allowed:
            raise ResourceError(
                f"Resource '{uri}' is not allowed in state '{self._state_machine.current_state}'. "
                f"Try `list/resources` first to check which resources are available."
            )

        resource = await self._resource_manager.get_resource(uri_str)
        if not resource:
            raise ResourceError(f"Unknown resource: {uri}")

        # Capture current state once for the transaction key
        current_state = self._state_machine.current_state

        # Outer: emit SUCCESS/ERROR transitions
        async with self._state_machine.transition_scope(
            success_symbol=InputSymbol.for_resource(uri_str, ResourceResultType.SUCCESS),
            error_symbol=InputSymbol.for_resource(uri_str, ResourceResultType.ERROR),
        ):
            # Inner: prepare/commit/abort transactions (loosely coupled, no machine dependency)
            async with AsyncTransactionScope(
                tx_manager=self._tx_manager,
                state=current_state,
                kind="resource",
                name=uri_str,
                ctx=ctx,
            ):
                content = await resource.read()
                return [ReadResourceContents(content=content, mime_type=resource.mime_type)]
