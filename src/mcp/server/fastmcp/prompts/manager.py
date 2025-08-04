"""Prompt management functionality."""

from typing import Any, overload

from pydantic import AnyUrl

from mcp.server.fastmcp.prompts.base import Message, Prompt
from mcp.server.fastmcp.uri_utils import filter_by_uri_paths, normalize_to_prompt_uri
from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class PromptManager:
    """Manages FastMCP prompts."""

    def __init__(self, warn_on_duplicate_prompts: bool = True):
        self._prompts: dict[str, Prompt] = {}
        self.warn_on_duplicate_prompts = warn_on_duplicate_prompts

    def _normalize_to_uri(self, name_or_uri: str) -> str:
        """Convert name to URI if needed."""
        return normalize_to_prompt_uri(name_or_uri)

    @overload
    def get_prompt(self, name_or_uri: str) -> Prompt | None:
        """Get prompt by name."""
        ...

    @overload
    def get_prompt(self, name_or_uri: AnyUrl) -> Prompt | None:
        """Get prompt by URI."""
        ...

    def get_prompt(self, name_or_uri: AnyUrl | str) -> Prompt | None:
        """Get prompt by name or URI."""
        if isinstance(name_or_uri, AnyUrl):
            return self._prompts.get(str(name_or_uri))

        # Try as a direct URI first
        if name_or_uri in self._prompts:
            return self._prompts[name_or_uri]

        # Try to find a prompt by name
        for prompt in self._prompts.values():
            if prompt.name == name_or_uri:
                return prompt

        # Finally try normalizing to URI
        uri = self._normalize_to_uri(name_or_uri)
        return self._prompts.get(uri)

    def list_prompts(self, uri_paths: list[AnyUrl] | None = None) -> list[Prompt]:
        """List all registered prompts, optionally filtered by URI paths."""
        prompts = list(self._prompts.values())
        if uri_paths:
            prompts = filter_by_uri_paths(prompts, uri_paths)
        logger.debug("Listing prompts", extra={"count": len(prompts), "uri_paths": uri_paths})
        return prompts

    def add_prompt(
        self,
        prompt: Prompt,
    ) -> Prompt:
        """Add a prompt to the manager."""
        logger.debug(f"Adding prompt: {prompt.name} with URI: {prompt.uri}")

        # Check for duplicates
        existing = self._prompts.get(str(prompt.uri))
        if existing:
            if self.warn_on_duplicate_prompts:
                logger.warning(f"Prompt already exists: {prompt.uri}")
            return existing

        self._prompts[str(prompt.uri)] = prompt
        return prompt

    @overload
    async def render_prompt(self, name_or_uri: str, arguments: dict[str, Any] | None = None) -> list[Message]:
        """Render a prompt by name with arguments."""
        ...

    @overload
    async def render_prompt(self, name_or_uri: AnyUrl, arguments: dict[str, Any] | None = None) -> list[Message]:
        """Render a prompt by URI with arguments."""
        ...

    async def render_prompt(self, name_or_uri: AnyUrl | str, arguments: dict[str, Any] | None = None) -> list[Message]:
        """Render a prompt by name or URI with arguments."""
        prompt = self.get_prompt(name_or_uri)
        if not prompt:
            raise ValueError(f"Unknown prompt: {name_or_uri}")

        return await prompt.render(arguments)
