from __future__ import annotations

from typing import Iterable, Optional

from pydantic import AnyUrl

from mcp.server.fastmcp.exceptions import ResourceError
from mcp.server.fastmcp.resources import Resource, ResourceManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.state.helper.extract_session_id import extract_session_id
from mcp.server.state.machine.state_machine import InputSymbol, StateMachine, SessionScope
from mcp.server.state.types import FastMCPContext, ResourceResultType
from mcp.server.state.transaction.async_transaction_scope import AsyncTransactionScope
from mcp.server.state.transaction.manager import TransactionManager

logger = get_logger(__name__)


def _sid(ctx: Optional[FastMCPContext]) -> Optional[str]:
    """Best-effort: extract session id from ctx; None on failure/missing."""
    if ctx is None:
        return None
    try:
        return extract_session_id(ctx)
    except Exception:
        return None


class StateAwareResourceManager:
    """State-aware **facade** over ``ResourceManager``.

    Wraps a ``StateMachine`` and delegates to the native manager while constraining
    discovery and reads by the machine's *current state*.

    Facade model (simplified):
    - Discovery via ``state_machine.available_symbols('resource')`` (URIs).
    - Outer: `AsyncTransactionScope` prepares (state, "resource", uri, outcome). PREPARE failure → stop.
    - Inner: `state_machine.step(...)` emits SUCCESS/ERROR around the read. Edge effects are best-effort.

    Session model:
    - Session is ambient (ContextVar). We bind per call via ``SessionScope(_sid(ctx))``.
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

    async def list_resources(self, ctx: Optional[FastMCPContext] = None) -> list[Resource]:
        """Return resources allowed in the **current state** (URIs via ``available_symbols('resource')``).

        Missing registrations are logged as warnings (soft), not raised.
        """
        with SessionScope(_sid(ctx)):
            allowed_uris = self._state_machine.available_symbols("resource")  # Set[str]
            out: list[Resource] = []
            for uri in allowed_uris:
                res = await self._resource_manager.get_resource(uri)
                if res is not None:
                    out.append(res)
                else:
                    logger.warning(
                        "Resource '%s' expected in state '%s' but not registered.",
                        uri,
                        self._state_machine.current_state(),
                    )
            return out

    async def read_resource(
        self,
        uri: str | AnyUrl,
        ctx: FastMCPContext,
    ) -> Iterable[ReadResourceContents]:
        """Read the resource in the **current state** with SUCCESS/ERROR step semantics."""
        with SessionScope(_sid(ctx)):
            allowed = self._state_machine.available_symbols("resource")
            uri_str = str(uri)
            if uri_str not in allowed:
                raise ResourceError(
                    f"Resource '{uri}' is not allowed in state '{self._state_machine.current_state()}'. "
                    f"Use list_resources() to inspect availability."
                )

            resource = await self._resource_manager.get_resource(uri_str)
            if not resource:
                raise ResourceError(f"Unknown resource: {uri}")

            current_state = self._state_machine.current_state()

            # OUTER: transactions (session-aware via ambient binding)
            async with AsyncTransactionScope(
                tx_manager=self._tx_manager,
                state=current_state,
                kind="resource",
                name=uri_str,
                ctx=ctx,
            ):
                # INNER: state step scope (effects can use ctx; scope does not rebind session)
                async with self._state_machine.step(
                    success_symbol=InputSymbol.for_resource(uri_str, ResourceResultType.SUCCESS),
                    error_symbol=InputSymbol.for_resource(uri_str, ResourceResultType.ERROR),
                    ctx=ctx,
                ):
                    content = await resource.read()
                    return [ReadResourceContents(content=content, mime_type=resource.mime_type)]
