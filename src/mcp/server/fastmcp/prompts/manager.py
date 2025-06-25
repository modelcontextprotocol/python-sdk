"""Prompt management functionality."""

from typing import Any

from mcp.server.fastmcp.authorizer import AllAllAuthorizer, Authorizer
from mcp.server.fastmcp.prompts.base import Message, Prompt
from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class PromptManager:
    """Manages FastMCP prompts."""

    def __init__(
        self,
        warn_on_duplicate_prompts: bool = True,
        authorizer: Authorizer = AllAllAuthorizer(),
    ):
        self._prompts: dict[str, Prompt] = {}
        self._authorizer = authorizer
        self.warn_on_duplicate_prompts = warn_on_duplicate_prompts

    def get_prompt(self, name: str) -> Prompt | None:
        """Get prompt by name."""
        if self._authorizer.permit_get_prompt(name):
            return self._prompts.get(name)
        else:
            return None

    def list_prompts(self) -> list[Prompt]:
        """List all registered prompts."""
        return [prompt for name, prompt in self._prompts.items() if self._authorizer.permit_list_prompt(name)]

    def add_prompt(
        self,
        prompt: Prompt,
    ) -> Prompt:
        """Add a prompt to the manager."""

        # Check for duplicates
        existing = self._prompts.get(prompt.name)
        if existing:
            if self.warn_on_duplicate_prompts:
                logger.warning(f"Prompt already exists: {prompt.name}")
            return existing

        self._prompts[prompt.name] = prompt
        return prompt

    async def render_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> list[Message]:
        """Render a prompt by name with arguments."""
        prompt = self.get_prompt(name)
        if not prompt:
            raise ValueError(f"Unknown prompt: {name}")
        if self._authorizer.permit_render_prompt(name, arguments):
            return await prompt.render(arguments)
        else:
            raise ValueError(f"Unknown prompt: {name}")
