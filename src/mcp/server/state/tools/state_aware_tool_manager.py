from __future__ import annotations

from typing import Any, Sequence

import mcp.types as types
from mcp.server.fastmcp.tools import Tool, ToolManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.machine.state_machine import InputSymbol, StateMachine
from mcp.server.state.types import FastMCPContext, ToolResultType
from mcp.server.state.transaction.async_transaction_scope import AsyncTransactionScope
from mcp.server.state.transaction.manager import TransactionManager

logger = get_logger(__name__)


class StateAwareToolManager:
    """State-aware **facade** over ``ToolManager``.

    Wraps a ``StateMachine`` (global or session-scoped) and delegates to the native
    ``ToolManager`` while constraining discovery/invocation by the machine's *current state*.

    Facade model:
    - Discovery: use ``state_machine.available_symbols("tool")`` to list allowed tool **names**.
    - Outer: `AsyncTransactionScope` prepares (state, "tool", name, outcome). On PREPARE failure → stop.
    - Inner: `state_machine.step(success_symbol, error_symbol, ctx=...)` drives SUCCESS/ERROR edges.
      Effects triggered by edges are fire-and-forget and must not affect state changes.
    """

    def __init__(
        self,
        state_machine: StateMachine,
        tool_manager: ToolManager,
        tx_manager: TransactionManager,
    ):
        self._tool_manager = tool_manager
        self._state_machine = state_machine
        self._tx_manager = tx_manager

    def list_tools(self) -> list[Tool]:
        """Return tools allowed in the **current state** (by name via ``available_symbols("tool")``).

        Missing registrations are logged as warnings (soft), not raised.
        """
        allowed_names = self._state_machine.available_symbols("tool")  # Set[str]
        available: list[Tool] = []
        for name in allowed_names:
            tool = self._tool_manager.get_tool(name)
            if tool:
                available.append(tool)
            else:
                logger.warning(
                    "Tool '%s' expected in state '%s' but not registered.",
                    name,
                    self._state_machine.current_state,
                )
        return available

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: FastMCPContext,
    ) -> Sequence[types.ContentBlock] | dict[str, Any]:
        """Execute the tool in the **current state** with SUCCESS/ERROR step semantics.

        Steps:
        1) Pre-validate: tool name must be in ``available_symbols('tool')`` and registered.
        2) Outer: `AsyncTransactionScope` (prepare/commit/abort).
        3) Inner: `state_machine.step(...)` emits SUCCESS/ERROR edges around the call.
        4) Execute the tool; convert results to MCP types if needed.
        """
        allowed = self._state_machine.available_symbols("tool")
        if name not in allowed:
            raise ValueError(
                f"Tool '{name}' is not allowed in state '{self._state_machine.current_state(ctx)}'. "
                f"Try `list/tools` first to inspect availability."
            )

        tool = self._tool_manager.get_tool(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found.")

        current_state = self._state_machine.current_state(ctx)

        # OUTER: transactions
        async with AsyncTransactionScope(
            tx_manager=self._tx_manager,
            state=current_state,
            kind="tool",
            name=name,
            ctx=ctx,
        ):
            # INNER: state step scope
            async with self._state_machine.step(
                success_symbol=InputSymbol.for_tool(name, ToolResultType.SUCCESS),
                error_symbol=InputSymbol.for_tool(name, ToolResultType.ERROR),
                ctx=ctx,
            ):
                return await tool.run(arguments, context=ctx, convert_result=True)
