from __future__ import annotations

from typing import Any, Sequence

import mcp.types as types
from mcp.server.fastmcp.tools import Tool, ToolManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state import InputSymbol, StateMachine, ToolResultType
from mcp.server.state.types import FastMCPContext
from mcp.server.state.transaction.async_transaction_scope import AsyncTransactionScope
from mcp.server.state.transaction.manager import TransactionManager

logger = get_logger(f"{__name__}.StateAwareToolManager")


class StateAwareToolManager:
    """State-aware facade over ``ToolManager`` (composition).

    Wraps a ``StateMachine`` (global or session-scoped) and delegates to the native
    ``ToolManager``; stays fully compatible with registrations and APIs.

    Composition model:
    - Validate access using the machine’s *current state*.
    - Wrap the operation with the machine’s **AsyncTransitionScope** to emit SUCCESS/ERROR.
    - Inside that, wrap with **AsyncTransactionScope** (loosely coupled; uses current state + kind/name).
    """

    def __init__(
            self, 
            state_machine: StateMachine, 
            tool_manager: ToolManager,
            tx_manager: TransactionManager
        ):
        self._tool_manager = tool_manager
        self._state_machine = state_machine
        self._tx_manager = tx_manager

    def list_tools(self) -> list[Tool]:
        """Return tools allowed in the **current_state**.

        Missing registrations are logged as warnings (soft), not raised.
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
        ctx: FastMCPContext,
    ) -> Sequence[types.ContentBlock] | dict[str, Any]:
        """
        Execute the tool in the **current state**:

        Steps
        -----
        1) **Pre-validate**: tool must be allowed by the state machine and registered.
        2) **Wrap with transitions**: `AsyncTransitionScope` emits SUCCESS/ERROR.
        3) **Wrap with transactions**: `AsyncTransactionScope` prepares/commits/aborts for (state, "tool", name).
           Any transaction error propagates, causing the transition scope to emit ERROR.

        Returns:
            Tool result (converted for MCP), or raises ValueError on validation/exec errors.
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

        # Capture the current state once for the transaction key
        current_state = self._state_machine.current_state

        # Outer: emit SUCCESS/ERROR transitions
        async with self._state_machine.transition_scope(
            success_symbol=InputSymbol.for_tool(name, ToolResultType.SUCCESS),
            error_symbol=InputSymbol.for_tool(name, ToolResultType.ERROR),
        ):
            # Inner: prepare/commit/abort transactions (loosely coupled, no machine dependency)
            async with AsyncTransactionScope(
                tx_manager=self._tx_manager,
                state=current_state,
                kind="tool",
                name=name,
                ctx=ctx,
            ):
                return await tool.run(arguments, context=ctx, convert_result=True)
