from typing import Any
from mcp.server.fastmcp.resources import Resource, ResourceManager
from mcp.server.state.state_machine import ResourceResultType, StateMachine, InputSymbol
from mcp.server.fastmcp.utilities.logging import get_logger

import mcp.types as types

logger = get_logger(__name__)

class StateAwareResourceManager:
    def __init__(self, state_machine: StateMachine, resource_manager: ResourceManager):
        self._resource_manager = resource_manager
        self._state_machine = state_machine

    def list_resources(self) -> list[Resource]:
        """Listet Ressourcen, die in der aktuellen StateMachine verfügbar sind."""

        resource_names = self._state_machine.get_available_inputs().get("resources", set())

        available_resources: list[Resource] = []
        for name in resource_names:
            # Ressourcen können sowohl über URI als auch Namen referenziert sein
            resource = self._get_resource_by_name(name)
            if resource:
                available_resources.append(resource)
            else:
                logger.warning(
                    f"Resource '{name}' was expected in '{self._state_machine.current_state}' but not present."
                )

        return available_resources

    async def get_resource(self, uri: str | Any) -> Any:
        """Lädt eine Resource und übergibt das Ergebnis als InputSymbol an die StateMachine."""
        result = None
        resultType = ResourceResultType.SUCCESS

        try:
            result = await self._resource_manager.get_resource(uri)
        except Exception as e:
            logger.exception(f"Exception during loading of resource '{uri}'")
            result = types.TextContent(type="text", text=str(e))
            resultType = ResourceResultType.ERROR

        symbol = InputSymbol.for_resource(str(uri), resultType)
        self._state_machine.transition(symbol)

        return result

    def _get_resource_by_name(self, name: str) -> Resource | None:
        """Hilfsfunktion, um eine Ressource anhand des Namens zu finden."""
        for res in self._resource_manager.list_resources():
            if res.name == name or str(res.uri) == name:
                return res
        return None

    
# TODO: ResourcesTemplates prüfen und ergänzen