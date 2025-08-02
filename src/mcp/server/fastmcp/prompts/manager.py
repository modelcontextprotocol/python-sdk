"""Prompt management functionality."""

from typing import Any

from mcp.server.fastmcp.prompts.base import Message, Prompt
from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class PromptManager:
    """Manages FastMCP prompts."""

    def __init__(self, warn_on_duplicate_prompts: bool = True):
        self._prompts: dict[str, Prompt] = {}
        self.warn_on_duplicate_prompts = warn_on_duplicate_prompts

    def _normalize_to_uri(self, name_or_uri: str) -> str:
        """Convert name to URI if needed."""
        if name_or_uri.startswith("prompt://"):
            return name_or_uri
        return f"prompt://{name_or_uri}"

    def get_prompt(self, name: str) -> Prompt | None:
        """Get prompt by name or URI."""
        uri = self._normalize_to_uri(name)
        return self._prompts.get(uri)

    def list_prompts(self, prefix: str | None = None) -> list[Prompt]:
        """List all registered prompts, optionally filtered by URI prefix."""
        prompts = list(self._prompts.values())
        if prefix:
            # Ensure prefix ends with / for proper path matching
            if not prefix.endswith("/"):
                prefix = prefix + "/"
            prompts = [p for p in prompts if str(p.uri).startswith(prefix)]
        logger.debug("Listing prompts", extra={"count": len(prompts), "prefix": prefix})
        return prompts

    def add_prompt(
        self,
        prompt: Prompt,
    ) -> Prompt:
        """Add a prompt to the manager."""
        logger.debug(f"Adding prompt: {prompt.name} with URI: {prompt.uri}")
        
        # Check for duplicates
        existing = self._prompts.get(prompt.uri)
        if existing:
            if self.warn_on_duplicate_prompts:
                logger.warning(f"Prompt already exists: {prompt.uri}")
            return existing

        self._prompts[prompt.uri] = prompt
        return prompt

    async def render_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> list[Message]:
        """Render a prompt by name with arguments."""
        prompt = self.get_prompt(name)
        if not prompt:
            raise ValueError(f"Unknown prompt: {name}")

        return await prompt.render(arguments)
