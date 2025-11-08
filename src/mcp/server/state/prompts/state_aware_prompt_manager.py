from __future__ import annotations

from typing import Any

import pydantic_core

from mcp.types import GetPromptResult
from mcp.server.fastmcp.prompts import Prompt, PromptManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.machine.state_machine import InputSymbol, StateMachine
from mcp.server.state.types import FastMCPContext, PromptResultType
from mcp.server.state.transaction.async_transaction_scope import AsyncTransactionScope
from mcp.server.state.transaction.manager import TransactionManager

logger = get_logger(__name__)


class StateAwarePromptManager:
    """State-aware **facade** over ``PromptManager``.

    Wraps a ``StateMachine`` and delegates to the native manager while
    constraining discovery and rendering by the machine's *current state*.

    Facade model:
    - Discovery: use ``state_machine.available_symbols("prompt")`` to list allowed prompt **names**.
    - Outer: `AsyncTransactionScope` prepares (state, "prompt", name, outcome). On PREPARE failure → stop.
    - Inner: `state_machine.step(success_symbol, error_symbol, ctx=...)` drives SUCCESS/ERROR edges.
      Effects triggered by edges are fire-and-forget and must not affect state changes.
    """

    def __init__(
        self,
        state_machine: StateMachine,
        prompt_manager: PromptManager,
        tx_manager: TransactionManager,
    ):
        self._prompt_manager = prompt_manager
        self._state_machine = state_machine
        self._tx_manager = tx_manager

    def list_prompts(self) -> list[Prompt]:
        """Return prompts allowed in the **current state** (by name via ``available_symbols("prompt")``).

        Missing registrations are logged as warnings (soft), not raised.
        """
        allowed_names = self._state_machine.available_symbols("prompt")  # Set[str]
        available: list[Prompt] = []
        for name in allowed_names:
            p = self._prompt_manager.get_prompt(name)
            if p is not None:
                available.append(p)
            else:
                logger.warning(
                    "Prompt '%s' expected in state '%s' but not registered.",
                    name,
                    self._state_machine.current_state,
                )
        return available

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: FastMCPContext,
    ) -> GetPromptResult:
        """Render the prompt in the **current state** with SUCCESS/ERROR step semantics.

        Steps:
        1) Pre-validate: name must be in ``available_symbols('prompt')`` and registered.
        2) Outer: `AsyncTransactionScope` (prepare/commit/abort) scoped to (state, "prompt", name).
        3) Inner: `state_machine.step(...)` emits SUCCESS/ERROR edges around the render.
        4) Render and convert to MCP types.
        """
        allowed = self._state_machine.available_symbols("prompt")
        if name not in allowed:
            raise ValueError(
                f"Prompt '{name}' is not allowed in state '{self._state_machine.current_state(ctx)}'. "
                f"Try `list/prompts` first to inspect availability."
            )

        prompt = self._prompt_manager.get_prompt(name)
        if not prompt:
            raise ValueError(f"Unknown prompt: {name}")

        current_state = self._state_machine.current_state(ctx)

        # OUTER: transactions
        async with AsyncTransactionScope(
            tx_manager=self._tx_manager,
            state=current_state,
            kind="prompt",
            name=name,
            ctx=ctx,
        ):
            # INNER: state step scope
            async with self._state_machine.step(
                success_symbol=InputSymbol.for_prompt(name, PromptResultType.SUCCESS),
                error_symbol=InputSymbol.for_prompt(name, PromptResultType.ERROR),
                ctx=ctx,
            ):
                messages = await prompt.render(arguments, context=ctx)
                return GetPromptResult(
                    description=prompt.description,
                    messages=pydantic_core.to_jsonable_python(messages),
                )
