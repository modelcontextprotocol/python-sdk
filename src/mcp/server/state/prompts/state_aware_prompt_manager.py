from __future__ import annotations

from typing import Any

import pydantic_core

from mcp.types import GetPromptResult
from mcp.server.fastmcp.prompts import Prompt, PromptManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.types import FastMCPContext
from mcp.server.state.machine.state_machine import (
    InputSymbol,
    PromptResultType,
    StateMachine,
)
from mcp.server.state.transaction.async_transaction_scope import AsyncTransactionScope
from mcp.server.state.transaction.manager import TransactionManager

logger = get_logger(f"{__name__}.StateAwarePromptManager")


class StateAwarePromptManager:
    """State-aware facade over ``PromptManager`` (composition).

    Wraps a ``StateMachine`` (global or session-scoped) and delegates to the native
    ``PromptManager`` while constraining visibility and execution by the machine's
    *current state*.

    Model:
    - Access is gated by the state machine.
    - The render call is wrapped by the machine’s **AsyncTransitionScope** (emits SUCCESS/ERROR).
    - Inside that, an **AsyncTransactionScope** prepares/commits/aborts for
      (state, "prompt", name). Any transaction failure bubbles up and causes
      the transition scope to emit the ERROR transition.
    """

    def __init__(
            self, 
            state_machine: StateMachine, 
            prompt_manager: PromptManager,
            tx_manager: TransactionManager
    ):
        self._prompt_manager = prompt_manager
        self._state_machine = state_machine
        self._tx_manager = tx_manager

    def list_prompts(self) -> list[Prompt]:
        """Return prompts allowed in the **current_state**.

        Missing registrations are logged as warnings (soft), not raised.
        """
        prompt_names = self._state_machine.get_available_inputs().get("prompts", set())

        available: list[Prompt] = []
        for name in prompt_names:
            prompt = self._prompt_manager.get_prompt(name)
            if prompt:
                available.append(prompt)
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
        """
        Render the prompt in the **current state**.

        Steps
        -----
        1) **Pre-validate**: prompt must be allowed by the state machine and registered.
        2) **Wrap with transitions**: `AsyncTransitionScope` emits SUCCESS/ERROR.
        3) **Wrap with transactions**: `AsyncTransactionScope` prepares/commits/aborts for
           (state, "prompt", name). Any transaction error propagates, causing ERROR transition.
        """
        allowed = self._state_machine.get_available_inputs().get("prompts", set())
        if name not in allowed:
            raise ValueError(
                f"Prompt '{name}' is not allowed in state '{self._state_machine.current_state}'. "
                f"Try `list/prompts` first to check which prompts are available."
            )

        prompt = self._prompt_manager.get_prompt(name)
        if not prompt:
            raise ValueError(f"Unknown prompt: {name}")

        # Capture current state once for the transaction key
        current_state = self._state_machine.current_state

        # Outer: emit SUCCESS/ERROR transitions
        async with self._state_machine.transition_scope(
            success_symbol=InputSymbol.for_prompt(name, PromptResultType.SUCCESS),
            error_symbol=InputSymbol.for_prompt(name, PromptResultType.ERROR),
        ):
            # Inner: prepare/commit/abort transactions (loosely coupled, no machine dependency)
            async with AsyncTransactionScope(
                tx_manager=self._tx_manager,
                state=current_state,
                kind="prompt",
                name=name,
                ctx=ctx,
            ):
                messages = await prompt.render(arguments, context=ctx)
                return GetPromptResult(
                    description=prompt.description,
                    messages=pydantic_core.to_jsonable_python(messages),
                )
