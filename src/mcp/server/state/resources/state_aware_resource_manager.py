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
    ``ResourceManager``; remains fully compatible with registrations and APIs.

    Composition model:
    - Validate access using the machine's *current state*.
    - **Outer:** `AsyncTransactionScope` prepares transactions for (state, "resource", uri, outcome).
      - If PREPARE fails, abort any partial preparations and raise → no transition emission, no read.
      - On exit: COMMIT the taken outcome, ABORT the other.
    - **Inner:** the machine's `AsyncTransitionScope` emits SUCCESS/ERROR (exact-match only, no DEFAULT),
      executes effects fire-and-forget, and resets to initial if a terminal state is reached.

    Note:
      Resource templates (``list_resource_templates``) are still handled by **FastMCP**.
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

        Steps:
        1) **Pre-validate**: resource must be allowed by the state machine and registered.
        2) **Transactions (outer)**: `AsyncTransactionScope` prepares for (state, "resource", uri, outcome).
           - PREPARE failure stops here (no transition emission, no resource read).
        3) **Transitions (inner)**: `AsyncTransitionScope` emits SUCCESS/ERROR (exact-match only).
           - Effects are fire-and-forget; failures are warnings and never affect state changes.
        4) Perform the resource read.
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

        # Capture current state once for transaction keying.
        current_state = self._state_machine.current_state

        # OUTER: prepare/commit/abort transactions (loosely coupled, no machine dependency).
        async with AsyncTransactionScope(
            tx_manager=self._tx_manager,
            state=current_state,
            kind="resource",
            name=uri_str,
            ctx=ctx,
        ):
            # INNER: emit SUCCESS/ERROR transitions (exact-match only; effects fire-and-forget).
            async with self._state_machine.transition_scope(
                success_symbol=InputSymbol.for_resource(uri_str, ResourceResultType.SUCCESS),
                error_symbol=InputSymbol.for_resource(uri_str, ResourceResultType.ERROR),
            ):
                content = await resource.read()
                return [ReadResourceContents(content=content, mime_type=resource.mime_type)]
