"""Prompt management functionality."""

from mcp.server.fastmcp.prompts.base import Prompt
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

    def add_prompt(self, prompt: Prompt) -> Prompt:
        """Add a prompt to the manager."""
        logger.debug(f"Adding prompt: {prompt.name} with URI: {prompt.uri}")
        existing = self._prompts.get(str(prompt.uri))
        if existing:
            if self.warn_on_duplicate_prompts:
                logger.warning(f"Prompt already exists: {prompt.uri}")
            return existing
        self._prompts[str(prompt.uri)] = prompt
        return prompt

    def get_prompt(self, name: str) -> Prompt | None:
        """Get prompt by name or URI."""
        uri = self._normalize_to_uri(name)
        return self._prompts.get(uri)

    def list_prompts(self, uri_paths: list[str] | None = None) -> list[Prompt]:
        """List all registered prompts, optionally filtered by URI paths."""
        prompts = list(self._prompts.values())
        prompts = filter_by_uri_paths(prompts, uri_paths, lambda p: p.uri)
        logger.debug("Listing prompts", extra={"count": len(prompts), "uri_paths": uri_paths})
        return prompts
