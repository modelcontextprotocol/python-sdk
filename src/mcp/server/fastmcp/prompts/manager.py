"""Prompt management functionality."""

from typing import Any

from mcp.server.fastmcp.prompts.base import Message, Prompt
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.types import AnyFunction

logger = get_logger(__name__)


class PromptManager:
    """Manages FastMCP prompts."""

    def __init__(self, warn_on_duplicate_prompts: bool = True):
        self._prompts: dict[str, Prompt] = {}
        self.warn_on_duplicate_prompts = warn_on_duplicate_prompts

    def get_prompt(self, name: str) -> Prompt | None:
        """Get prompt by name."""
        return self._prompts.get(name)

    def list_prompts(self) -> list[Prompt]:
        """List all registered prompts."""
        return list(self._prompts.values())

    def add_prompt(
        self,
        prompt_or_fn: Prompt | AnyFunction,
        name: str | None = None,
        description: str | None = None,
    ) -> Prompt:
        """Add a prompt to the manager.

        Args:
            prompt_or_fn: Either a Prompt instance or a function to create a prompt from
            name: Optional name for the prompt (only used if prompt_or_fn is a function)
            description: Optional description of the prompt
                         (only used if prompt_or_fn is a function)
        """
        if isinstance(prompt_or_fn, Prompt):
            prompt = prompt_or_fn
        else:
            prompt = Prompt.from_function(
                prompt_or_fn, name=name, description=description
            )

        # Check for duplicates
        existing = self._prompts.get(prompt.name)
        if existing:
            if self.warn_on_duplicate_prompts:
                logger.warning(f"Prompt already exists: {prompt.name}")
            return existing

        self._prompts[prompt.name] = prompt
        return prompt

    async def render_prompt(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> list[Message]:
        """Render a prompt by name with arguments."""
        prompt = self.get_prompt(name)
        if not prompt:
            raise ValueError(f"Unknown prompt: {name}")

        return await prompt.render(arguments)
