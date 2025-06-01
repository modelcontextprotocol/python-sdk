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
        prompt: Prompt | None = None,
        fn: AnyFunction | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> Prompt:
        """Add a prompt to the manager.

        Args:
            prompt: A Prompt instance (required if fn is not provided)
            fn: A function to create a prompt from (required if prompt is not provided)
            name: Optional name for the prompt (only used if fn is provided)
            description: Optional description of the prompt (only used if fn is provided)
        """
        if prompt is None and fn is None:
            raise ValueError("Either prompt or fn must be provided")
        if prompt is not None and fn is not None:
            raise ValueError("Cannot provide both prompt and fn")

        if prompt is None:
            # Only call from_function if we have a function to convert
            prompt = Prompt.from_function(
                fn,  # type: ignore[arg-type]
                name=name,
                description=description,
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
