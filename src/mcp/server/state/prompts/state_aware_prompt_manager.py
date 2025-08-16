from __future__ import annotations

from typing import Any

import pydantic_core
from mcp.types import GetPromptResult
from mcp.server.fastmcp.prompts import Prompt, PromptManager
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.machine import InputSymbol, PromptResultType, StateMachine

logger = get_logger(f"{__name__}.StateAwarePromptManager")

class StateAwarePromptManager:
    """State-aware facade over ``PromptManager`` (composition).

    Wraps a ``StateMachine`` (global or session-scoped) and delegates to the native
    ``PromptManager``; stays fully compatible with registrations and APIs.
    """

    def __init__(self, state_machine: StateMachine, prompt_manager: PromptManager):
        self._prompt_manager = prompt_manager
        self._state_machine = state_machine

    def list_prompts(self) -> list[Prompt]:
        """Return prompts allowed in the **current_state**.

        - Missing registrations are logged as warnings (soft), not raised as errors.
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


    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> GetPromptResult:
        """
        Execute the prompt in the **current state**:

        - **Pre-validate**: ensure prompt is allowed and available in the current state; otherwise raise ``ValueError``.
        - **Execute**: resolve the prompt and render it with ``arguments``.
        - **Transition**: emit ``SUCCESS`` or ``ERROR`` via ``InputSymbol.for_prompt(...)`` to drive a state transition.
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

        try:
            messages = await prompt.render(arguments)

            self._state_machine.transition(InputSymbol.for_prompt(name, PromptResultType.SUCCESS))
            return GetPromptResult(
                description=prompt.description,
                messages=pydantic_core.to_jsonable_python(messages),
            )
        except Exception as e:
            self._state_machine.transition(InputSymbol.for_prompt(name, PromptResultType.ERROR))
            logger.exception("Error getting prompt %s", name)
            raise ValueError(str(e)) from e
