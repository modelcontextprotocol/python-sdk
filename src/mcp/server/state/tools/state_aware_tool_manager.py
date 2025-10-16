from __future__ import annotations

from typing import Any, Sequence

import mcp.types as types
from mcp.server.fastmcp.tools import Tool, ToolManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state import InputSymbol, StateMachine, ToolResultType
from mcp.server.state.types import FastMCPContext


logger = get_logger(f"{__name__}.StateAwareToolManager")

class StateAwareToolManager:
    """State-aware facade over ``ToolManager`` (composition).

    Wraps a ``StateMachine`` (global or session-scoped) and delegates to the native
    ``ToolManager``; stays fully compatible with registrations and APIs.
    """

    def __init__(self, state_machine: StateMachine, tool_manager: ToolManager):
        self._tool_manager = tool_manager
        self._state_machine = state_machine

    def list_tools(self) -> list[Tool]:
        """Return tools allowed in the **current_state**.

        - Missing registrations are logged as warnings (soft), not raised as errors.
        """
        tool_names = self._state_machine.get_available_inputs().get("tools", set())

        available_tools: list[Tool] = []
        for name in tool_names:
            tool = self._tool_manager.get_tool(name)
            if tool:
                available_tools.append(tool)
            else:
                logger.warning(
                    "Tool '%s' expected in state '%s' but not registered.",
                    name,
                    self._state_machine.current_state,
                )
        return available_tools


    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: FastMCPContext
    ) -> Sequence[types.ContentBlock] | dict[str, Any]:
        """
        Execute the tool in the **current state**:

        - **Pre-validate**: ensure tool is allowed and available in the current state; otherwise raise ``ValueError``.
        - **Execute**: resolve the tool and run it with ``arguments`` and ``ctx``.
        - **Transition**: SUCCESS/ERROR are emitted via the state's async transition scope.
        """
        allowed = self._state_machine.get_available_inputs().get("tools", set())
        if name not in allowed:
            raise ValueError(
                f"Tool '{name}' is not allowed in state '{self._state_machine.current_state}'. "
                f"Try `list/tools` first to check which tools are available."
            )

        tool = self._tool_manager.get_tool(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found.")

        async with self._state_machine.transition_scope(
            success_symbol=InputSymbol.for_tool(name, ToolResultType.SUCCESS),
            error_symbol=InputSymbol.for_tool(name, ToolResultType.ERROR),
        ):
            return await tool.run(arguments, context=ctx, convert_result=True)

