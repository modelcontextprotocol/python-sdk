from typing import Any
from mcp.server.fastmcp.tools import Tool, ToolManager  # Der native ToolManager
from mcp.server.state.state_machine import ToolResultType, StateMachine, InputSymbol
from mcp.server.fastmcp.utilities.logging import get_logger

import mcp.types as types

logger = get_logger(__name__)

class StateAwareToolManager:
    def __init__(self, state_machine: StateMachine, tool_manager: ToolManager):
        self._tool_manager = tool_manager
        self._state_machine = state_machine

    def list_tools(self) -> list[Tool]:
        """Listet Tools, die in der aktuellen StateMachine verfügbar sind."""

        tool_names = self._state_machine.get_available_inputs().get("tools", set())

        available_tools: list[Tool] = []
        for name in tool_names:
            tool = self._tool_manager.get_tool(name)
            if tool:
                available_tools.append(tool)
            else:
                logger.warning(f"Tool '{name}' was expected in'{self._state_machine.current_state}' but not present.")

        return available_tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Führt ein Tool aus und übergibt das Ergebnis der StateMachine als InputSymbol."""
        result = None
        resultType = ToolResultType.SUCCESS

        tool = self._tool_manager.get_tool(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found.")

        try:
            result = await tool.run(arguments, context=None, convert_result=True)
        except Exception as e:
            logger.exception(f"Exception during execution of tool '{name}'")
            result = types.TextContent(type="text", text=str(e))
            resultType = ToolResultType.ERROR

        symbol = InputSymbol.for_tool(name, resultType)
        self._state_machine.transition(symbol)

        return result
