import pytest

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.prompts.base import Prompt, UserMessage
from mcp.server.mcpserver.prompts.manager import PromptManager
from mcp.types import TextContent


class TestPromptManager:
    def test_add_prompt(self):
        """Test adding a prompt to the manager."""

        def fn() -> str:  # pragma: no cover
            return "Hello, world!"

        manager = PromptManager()
        prompt = Prompt.from_function(fn)
        added = manager.add_prompt(prompt)
        assert added == prompt
        assert manager.get_prompt("fn") == prompt

    def test_add_duplicate_prompt(self, caplog: pytest.LogCaptureFixture):
        """Test adding the same prompt twice."""

        def fn() -> str:  # pragma: no cover
            return "Hello, world!"

        manager = PromptManager()
        prompt = Prompt.from_function(fn)
        first = manager.add_prompt(prompt)
        second = manager.add_prompt(prompt)
        assert first == second
        assert "Prompt already exists" in caplog.text

    def test_disable_warn_on_duplicate_prompts(self, caplog: pytest.LogCaptureFixture):
        """Test disabling warning on duplicate prompts."""

        def fn() -> str:  # pragma: no cover
            return "Hello, world!"

        manager = PromptManager(warn_on_duplicate_prompts=False)
        prompt = Prompt.from_function(fn)
        first = manager.add_prompt(prompt)
        second = manager.add_prompt(prompt)
        assert first == second
        assert "Prompt already exists" not in caplog.text

    def test_list_prompts(self):
        """Test listing all prompts."""

        def fn1() -> str:  # pragma: no cover
            return "Hello, world!"

        def fn2() -> str:  # pragma: no cover
            return "Goodbye, world!"

        manager = PromptManager()
        prompt1 = Prompt.from_function(fn1)
        prompt2 = Prompt.from_function(fn2)
        manager.add_prompt(prompt1)
        manager.add_prompt(prompt2)
        prompts = manager.list_prompts()
        assert len(prompts) == 2
        assert prompts == [prompt1, prompt2]

    @pytest.mark.anyio
    async def test_render_prompt(self):
        """Test rendering a prompt."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager()
        prompt = Prompt.from_function(fn)
        manager.add_prompt(prompt)
        messages = await manager.render_prompt("fn", None, Context())
        assert messages == [UserMessage(content=TextContent(type="text", text="Hello, world!"))]

    @pytest.mark.anyio
    async def test_render_prompt_with_args(self):
        """Test rendering a prompt with arguments."""

        def fn(name: str) -> str:
            return f"Hello, {name}!"

        manager = PromptManager()
        prompt = Prompt.from_function(fn)
        manager.add_prompt(prompt)
        messages = await manager.render_prompt("fn", {"name": "World"}, Context())
        assert messages == [UserMessage(content=TextContent(type="text", text="Hello, World!"))]

    @pytest.mark.anyio
    async def test_render_unknown_prompt(self):
        """Test rendering a non-existent prompt."""
        manager = PromptManager()
        with pytest.raises(ValueError, match="Unknown prompt: unknown"):
            await manager.render_prompt("unknown", None, Context())

    @pytest.mark.anyio
    async def test_render_prompt_with_missing_args(self):
        """Test rendering a prompt with missing required arguments."""

        def fn(name: str) -> str:  # pragma: no cover
            return f"Hello, {name}!"

        manager = PromptManager()
        prompt = Prompt.from_function(fn)
        manager.add_prompt(prompt)
        with pytest.raises(ValueError, match="Missing required arguments"):
            await manager.render_prompt("fn", None, Context())


class TestRemovePrompt:
    """Test PromptManager.remove_prompt() functionality."""

    def test_remove_existing_prompt(self):
        """Test removing an existing prompt."""

        def fn() -> str:  # pragma: no cover
            return "Hello, world!"

        manager = PromptManager()
        prompt = Prompt.from_function(fn)
        manager.add_prompt(prompt)

        # Verify prompt exists
        assert manager.get_prompt("fn") is not None
        assert len(manager.list_prompts()) == 1

        # Remove the prompt - should not raise any exception
        manager.remove_prompt("fn")

        # Verify prompt is removed
        assert manager.get_prompt("fn") is None
        assert len(manager.list_prompts()) == 0

    def test_remove_nonexistent_prompt(self):
        """Test removing a non-existent prompt raises error."""
        manager = PromptManager()

        with pytest.raises(Exception, match="Unknown prompt: nonexistent"):
            manager.remove_prompt("nonexistent")

    def test_remove_one_prompt_from_multiple(self):
        """Test removing one prompt when multiple prompts exist."""

        def fn1() -> str:  # pragma: no cover
            return "Hello, world!"

        def fn2() -> str:  # pragma: no cover
            return "Goodbye, world!"

        def fn3() -> str:  # pragma: no cover
            return "How are you?"

        manager = PromptManager()
        prompt1 = Prompt.from_function(fn1)
        prompt2 = Prompt.from_function(fn2)
        prompt3 = Prompt.from_function(fn3)
        manager.add_prompt(prompt1)
        manager.add_prompt(prompt2)
        manager.add_prompt(prompt3)

        # Verify all prompts exist
        assert len(manager.list_prompts()) == 3
        assert manager.get_prompt("fn1") is not None
        assert manager.get_prompt("fn2") is not None
        assert manager.get_prompt("fn3") is not None

        # Remove middle prompt
        manager.remove_prompt("fn2")

        # Verify only fn2 is removed
        assert len(manager.list_prompts()) == 2
        assert manager.get_prompt("fn1") is not None
        assert manager.get_prompt("fn2") is None
        assert manager.get_prompt("fn3") is not None
