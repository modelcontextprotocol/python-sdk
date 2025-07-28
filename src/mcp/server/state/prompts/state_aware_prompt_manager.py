from typing import Any
from mcp.server.fastmcp.prompts import Prompt, PromptManager
from mcp.server.state.state_machine import PromptResultType, StateMachine, InputSymbol
from mcp.server.fastmcp.utilities.logging import get_logger

import mcp.types as types

logger = get_logger(__name__)

class StateAwarePromptManager:
    def __init__(self, state_machine: StateMachine, prompt_manager: PromptManager):
        self._prompt_manager = prompt_manager
        self._state_machine = state_machine

    def list_prompts(self) -> list[Prompt]:
        """Listet Prompts, die in der aktuellen StateMachine verfügbar sind."""
        prompt_names = self._state_machine.get_available_inputs().get("prompts", set())

        available_prompts: list[Prompt] = []
        for name in prompt_names:
            prompt = self._prompt_manager.get_prompt(name)
            if prompt:
                available_prompts.append(prompt)
            else:
                logger.warning(
                    f"Prompt '{name}' was expected in '{self._state_machine.current_state}' but not present."
                )

        return available_prompts

    async def call_prompt(self, name: str, arguments: dict[str, Any]) -> Any:
        """Führt einen Prompt aus und übergibt das Ergebnis als InputSymbol an die StateMachine."""
        result = None
        resultType = PromptResultType.SUCCESS

        prompt = self._prompt_manager.get_prompt(name)
        if not prompt:
            raise ValueError(f"Prompt '{name}' not found.")

        try:
            result = await prompt.render(arguments)
        except Exception as e:
            logger.exception(f"Exception during rendering of prompt '{name}'")
            result = types.TextContent(type="text", text=str(e))
            resultType = PromptResultType.ERROR

        symbol = InputSymbol.for_prompt(name, resultType)
        self._state_machine.transition(symbol)

        return result
