from __future__ import annotations

from typing import Any, Optional

import pydantic_core

from mcp.types import GetPromptResult
from mcp.server.fastmcp.prompts import Prompt, PromptManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.helper.extract_session_id import extract_session_id
from mcp.server.state.machine.state_machine import InputSymbol, StateMachine, SessionScope
from mcp.server.state.types import FastMCPContext, PromptResultType
from mcp.server.state.transaction.async_transaction_scope import AsyncTransactionScope
from mcp.server.state.transaction.manager import TransactionManager

logger = get_logger(__name__)


def _sid(ctx: Optional[FastMCPContext]) -> Optional[str]:
    try:
        return extract_session_id(ctx) if ctx is not None else None
    except Exception:
        return None


class StateAwarePromptManager:
    """State-aware **facade** over ``PromptManager``.

    Wraps a ``StateMachine`` and delegates to the native manager while constraining
    discovery and rendering by the machine's *current state*.

    Facade model:
    - Discovery via ``state_machine.available_symbols('prompt')`` (names).
    - Outer: `AsyncTransactionScope` prepares (state, "prompt", name, outcome). PREPARE failure → stop.
    - Inner: `state_machine.step(...)` emits SUCCESS/ERROR around render. Edge effects are best-effort.

    Session model: ambient via ``SessionScope(_sid(ctx))`` per call.
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

    def list_prompts(self, ctx: Optional[FastMCPContext] = None) -> list[Prompt]:
        """Return prompts allowed in the **current state** (names via ``available_symbols('prompt')``)."""
        with SessionScope(_sid(ctx)):
            allowed_names = self._state_machine.available_symbols("prompt")  # Set[str]
            out: list[Prompt] = []
            for name in allowed_names:
                p = self._prompt_manager.get_prompt(name)
                if p is not None:
                    out.append(p)
                else:
                    logger.warning(
                        "Prompt '%s' expected in state '%s' but not registered.",
                        name,
                        self._state_machine.current_state(),
                    )
            return out

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: FastMCPContext,
    ) -> GetPromptResult:
        """Render the prompt in the **current state** with SUCCESS/ERROR step semantics."""
        with SessionScope(_sid(ctx)):
            allowed = self._state_machine.available_symbols("prompt")
            if name not in allowed:
                raise ValueError(
                    f"Prompt '{name}' is not allowed in state '{self._state_machine.current_state()}'. "
                    f"Use list_prompts() to inspect availability."
                )

            prompt = self._prompt_manager.get_prompt(name)
            if not prompt:
                raise ValueError(f"Unknown prompt: {name}")

            current_state = self._state_machine.current_state()

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
