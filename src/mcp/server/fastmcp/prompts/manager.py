"""Prompt management functionality for FastMCP servers.

This module provides the PromptManager class, which serves as the central registry
for managing prompts in FastMCP servers. Prompts are reusable templates that generate
structured messages for AI model interactions, enabling consistent and parameterized
communication patterns.

The PromptManager handles the complete lifecycle of prompts:

- Registration and storage of prompt templates
- Retrieval by name for use in MCP protocol handlers
- Rendering with arguments to produce message sequences
- Duplicate detection and management

Key concepts:

- Prompts are created from functions using Prompt.from_function()
- Each prompt has a unique name used for registration and retrieval
- Prompts can accept typed arguments for dynamic content generation
- Rendered prompts return Message objects ready for AI model consumption

Examples:
    Basic prompt management workflow:

    ```python
    from mcp.server.fastmcp.prompts import PromptManager, Prompt

    # Initialize the manager
    manager = PromptManager()

    # Create a prompt from a function
    def analysis_prompt(topic: str, context: str) -> list[str]:
        return [
            f"Please analyze the following topic: {topic}",
            f"Additional context: {context}",
            "Provide a detailed analysis with key insights."
        ]

    # Register the prompt
    prompt = Prompt.from_function(analysis_prompt)
    manager.add_prompt(prompt)

    # Render the prompt with arguments
    messages = await manager.render_prompt(
        "analysis_prompt",
        {"topic": "AI Safety", "context": "Enterprise deployment"}
    )
    ```

    Integration with FastMCP servers:

    ```python
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("My Server")

    @mcp.prompt()
    def code_review(language: str, code: str) -> str:
        return f"Review this {language} code for best practices:\\n\\n{code}"

    # The prompt is automatically registered with the server's PromptManager
    ```

Note:
    This module is primarily used internally by FastMCP servers, but can be used
    directly for advanced prompt management scenarios or custom MCP implementations.
"""

from typing import Any

from mcp.server.fastmcp.prompts.base import Message, Prompt
from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class PromptManager:
    """Manages prompt registration, storage, and rendering for FastMCP servers.

    The PromptManager is the central registry for all prompts in a FastMCP server. It handles
    prompt registration, retrieval by name, listing all available prompts, and rendering
    prompts with provided arguments. Prompts are templates that can generate structured
    messages for AI model interactions.

    This class is typically used internally by FastMCP servers but can be used directly
    for advanced prompt management scenarios.

    Args:
        warn_on_duplicate_prompts: Whether to log warnings when attempting to register
            a prompt with a name that already exists. Defaults to True.

    Attributes:
        warn_on_duplicate_prompts: Whether duplicate prompt warnings are enabled.

    Examples:
        Basic usage:

        ```python
        from mcp.server.fastmcp.prompts import PromptManager, Prompt

        # Create a manager
        manager = PromptManager()

        # Create and add a prompt
        def greeting_prompt(name: str) -> str:
            return f"Hello, {name}! How can I help you today?"

        prompt = Prompt.from_function(greeting_prompt)
        manager.add_prompt(prompt)

        # Render the prompt
        messages = await manager.render_prompt("greeting_prompt", {"name": "Alice"})
        ```

        Disabling duplicate warnings:

        ```python
        # Useful in testing scenarios or when you need to replace prompts
        manager = PromptManager(warn_on_duplicate_prompts=False)
        ```
    """

    def __init__(self, warn_on_duplicate_prompts: bool = True):
        self._prompts: dict[str, Prompt] = {}
        self.warn_on_duplicate_prompts = warn_on_duplicate_prompts

    def get_prompt(self, name: str) -> Prompt | None:
        """Retrieve a registered prompt by its name.

        Args:
            name: The name of the prompt to retrieve.

        Returns:
            The Prompt object if found, None if no prompt exists with the given name.
        """
        return self._prompts.get(name)

    def list_prompts(self) -> list[Prompt]:
        """Get a list of all registered prompts.

        Returns:
            A list containing all Prompt objects currently registered with this manager.
            Returns an empty list if no prompts are registered.
        """
        return list(self._prompts.values())

    def add_prompt(
        self,
        prompt: Prompt,
    ) -> Prompt:
        """Register a prompt with the manager.

        If a prompt with the same name already exists, the existing prompt is returned
        without modification. A warning is logged if warn_on_duplicate_prompts is True.

        Args:
            prompt: The Prompt object to register.

        Returns:
            The registered Prompt object. If a prompt with the same name already exists,
            returns the existing prompt instead of the new one.
        """

        # Check for duplicates
        existing = self._prompts.get(prompt.name)
        if existing:
            if self.warn_on_duplicate_prompts:
                logger.warning(f"Prompt already exists: {prompt.name}")
            return existing

        self._prompts[prompt.name] = prompt
        return prompt

    async def render_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> list[Message]:
        """Render a prompt into a list of messages ready for AI model consumption.

        This method looks up the prompt by name, validates that all required arguments
        are provided, executes the prompt function with the given arguments, and converts
        the result into a standardized list of Message objects.

        Args:
            name: The name of the prompt to render.
            arguments: Optional dictionary of arguments to pass to the prompt function.
                Must include all required arguments defined by the prompt.

        Returns:
            A list of Message objects containing the rendered prompt content.
            Each Message has a role ("user" or "assistant") and content.

        Raises:
            ValueError: If the prompt name is not found or if required arguments are missing.

        Examples:
            Simple prompt without arguments:

            ```python
            messages = await manager.render_prompt("welcome")
            ```

            Prompt with arguments:

            ```python
            messages = await manager.render_prompt(
                "greeting",
                {"name": "Alice", "language": "en"}
            )
            ```
        """
        prompt = self.get_prompt(name)
        if not prompt:
            raise ValueError(f"Unknown prompt: {name}")

        return await prompt.render(arguments)
