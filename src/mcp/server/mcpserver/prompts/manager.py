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

    Prompts are stored in a nested dict: ``{tenant_id: {prompt_name: Prompt}}``.
    This allows the same prompt name to exist independently under different
    tenants with O(1) lookups per tenant. When ``tenant_id`` is ``None``
    (the default), prompts live in a global scope, preserving backward
    compatibility with single-tenant usage.

    Note: This class is not thread-safe. It is designed to run within a
    single-threaded async event loop, where all synchronous mutations
    execute atomically. Do not share instances across OS threads without
    external synchronization.
    """

    def __init__(self, warn_on_duplicate_prompts: bool = True):
        self._prompts: dict[str | None, dict[str, Prompt]] = {}
        self.warn_on_duplicate_prompts = warn_on_duplicate_prompts

    def get_prompt(self, name: str, *, tenant_id: str | None = None) -> Prompt | None:
        """Get prompt by name, optionally scoped to a tenant."""
        return self._prompts.get(tenant_id, {}).get(name)

    def list_prompts(self, *, tenant_id: str | None = None) -> list[Prompt]:
        """List all registered prompts for a given tenant scope."""
        return list(self._prompts.get(tenant_id, {}).values())

    def add_prompt(
        self,
        prompt: Prompt,
        *,
        tenant_id: str | None = None,
    ) -> Prompt:
        """Add a prompt to the manager, optionally scoped to a tenant."""
        scope = self._prompts.setdefault(tenant_id, {})
        existing = scope.get(prompt.name)
        if existing:
            if self.warn_on_duplicate_prompts:
                logger.warning(f"Prompt already exists: {prompt.name}")
            return existing

        scope[prompt.name] = prompt
        return prompt

    def remove_prompt(self, name: str, *, tenant_id: str | None = None) -> None:
        """Remove a prompt by name, optionally scoped to a tenant."""
        scope = self._prompts.get(tenant_id, {})
        if name not in scope:
            raise ValueError(f"Unknown prompt: {name}")
        del scope[name]
        if not scope and tenant_id in self._prompts:
            del self._prompts[tenant_id]

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
