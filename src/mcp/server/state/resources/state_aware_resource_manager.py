from __future__ import annotations

from pydantic import AnyUrl
from typing import Iterable

from mcp.server.fastmcp.exceptions import ResourceError
from mcp.server.fastmcp.resources import Resource, ResourceManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.state.machine import InputSymbol, ResourceResultType, StateMachine

logger = get_logger(f"{__name__}.StateAwareResourceManager")

class StateAwareResourceManager:
    """State-aware facade over ``ResourceManager`` (composition).

    Wraps a ``StateMachine`` (global or session-scoped) and delegates to the native
    ``ResourceManager``; stays fully compatible with registrations and APIs.

    **Note:** Resource templates (``list_resource_templates``) are not overridden here and
    continue to be handled by **FastMCP** until semantics are finalized.
    """

    def __init__(self, state_machine: StateMachine, resource_manager: ResourceManager):
        self._resource_manager = resource_manager
        self._state_machine = state_machine

    async def list_resources(self) -> list[Resource]:
        """Return resources allowed in the **current_state**.

        - Missing registrations are logged as warnings (soft), not raised as errors.
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

    async def read_resource(self, uri: str | AnyUrl) -> Iterable[ReadResourceContents]:
        """
        Read the resource in the **current state**:

        - **Pre-validate**: ensure resource is allowed and available in the current state; otherwise raise ``ResourceError``.
        - **Execute**: resolve the resource and read its content.
        - **Transition**: emit ``SUCCESS`` or ``ERROR`` via ``InputSymbol.for_resource(...)`` to drive a state transition.
        """
        allowed = self._state_machine.get_available_inputs().get("resources", set())
        if str(uri) not in allowed:
            raise ResourceError(
                f"Resource '{uri}' is not allowed in state '{self._state_machine.current_state}'. "
                f"Try `list/resources` first to check which resources are available."
            )
        
        resource = await self._resource_manager.get_resource(uri)
        if not resource:
            raise ResourceError(f"Unknown resource: {uri}")

        try:
            content = await resource.read()
            self._state_machine.transition(InputSymbol.for_resource(str(uri), ResourceResultType.SUCCESS))

            return [ReadResourceContents(content=content, mime_type=resource.mime_type)]
        except Exception as e:
            self._state_machine.transition(InputSymbol.for_resource(str(uri), ResourceResultType.ERROR))
            logger.exception("Error reading resource %s", uri)
            raise ResourceError(str(e)) from e

