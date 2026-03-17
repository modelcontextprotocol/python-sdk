"""Prompt management functionality."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver.prompts.base import Message, Prompt
from mcp.server.mcpserver.utilities.logging import get_logger

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.context import Context

logger = get_logger(__name__)


class PromptManager:
    """Manages MCPServer prompts with optional tenant-scoped storage.

    Prompts are stored in a dict keyed by ``(tenant_id, prompt_name)``.
    This allows the same prompt name to exist independently under different
    tenants. When ``tenant_id`` is ``None`` (the default), prompts live in
    a global scope, preserving backward compatibility with single-tenant usage.
    """

    def __init__(self, warn_on_duplicate_prompts: bool = True):
        self._prompts: dict[tuple[str | None, str], Prompt] = {}
        self.warn_on_duplicate_prompts = warn_on_duplicate_prompts

    def get_prompt(self, name: str, *, tenant_id: str | None = None) -> Prompt | None:
        """Get prompt by name, optionally scoped to a tenant."""
        return self._prompts.get((tenant_id, name))

    def list_prompts(self, *, tenant_id: str | None = None) -> list[Prompt]:
        """List all registered prompts for a given tenant scope."""
        return [prompt for (tid, _), prompt in self._prompts.items() if tid == tenant_id]

    def add_prompt(
        self,
        prompt: Prompt,
        *,
        tenant_id: str | None = None,
    ) -> Prompt:
        """Add a prompt to the manager, optionally scoped to a tenant."""

        # Check for duplicates
        key = (tenant_id, prompt.name)
        existing = self._prompts.get(key)
        if existing:
            if self.warn_on_duplicate_prompts:
                logger.warning(f"Prompt already exists: {prompt.name}")
            return existing

        self._prompts[key] = prompt
        return prompt

    async def render_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        context: Context[LifespanContextT, RequestT],
        *,
        tenant_id: str | None = None,
    ) -> list[Message]:
        """Render a prompt by name with arguments, optionally scoped to a tenant."""
        prompt = self.get_prompt(name, tenant_id=tenant_id)
        if not prompt:
            raise ValueError(f"Unknown prompt: {name}")

        return await prompt.render(arguments, context)
