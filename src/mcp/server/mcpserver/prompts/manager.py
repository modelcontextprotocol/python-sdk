"""Prompt management functionality."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver.prompts.base import Message, Prompt
from mcp.server.mcpserver.utilities.logging import get_logger

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.server import Context

logger = get_logger(__name__)


class PromptManager:
    """Manages MCPServer prompts."""

    def __init__(
        self,
        warn_on_duplicate_prompts: bool = True,
        dependency_overrides: dict[Callable[..., Any], Callable[..., Any]] | None = None,
    ):
        self._prompts: dict[str, Prompt] = {}
        self.warn_on_duplicate_prompts = warn_on_duplicate_prompts
        self.dependency_overrides = dependency_overrides if dependency_overrides is not None else {}

    def get_prompt(self, name: str) -> Prompt | None:
        """Get prompt by name."""
        return self._prompts.get(name)

    def list_prompts(self) -> list[Prompt]:
        """List all registered prompts."""
        return list(self._prompts.values())

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

    async def render_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        context: Context[LifespanContextT, RequestT] | None = None,
    ) -> list[Message]:
        """Render a prompt by name with arguments."""
        prompt = self.get_prompt(name)
        if not prompt:
            raise ValueError(f"Unknown prompt: {name}")

        # Create dependency resolver if prompt has dependencies
        dependency_resolver = None
        if prompt.dependency_kwarg_names:  # pragma: no cover
            from mcp.server.mcpserver.utilities.dependency_resolver import DependencyResolver

            dependency_resolver = DependencyResolver(context=context, overrides=self.dependency_overrides)

        return await prompt.render(arguments, context=context, dependency_resolver=dependency_resolver)
