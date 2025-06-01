"""Tests for prompt manager."""

import pytest

from mcp.server.fastmcp.prompts.manager import PromptManager


class TestPromptManager:
    """Test prompt manager functionality."""

    def test_add_prompt(self):
        """Test adding a prompt to the manager."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager()
        added = manager.add_prompt(fn=fn)

        assert added.name == "fn"
        assert added.description == ""
        assert len(manager.list_prompts()) == 1

    def test_add_prompt_with_name(self):
        """Test adding a prompt with a custom name."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager()
        added = manager.add_prompt(fn=fn, name="greeting")

        assert added.name == "greeting"
        assert added.description == ""
        assert len(manager.list_prompts()) == 1

    def test_add_prompt_with_description(self):
        """Test adding a prompt with a description."""

        def fn() -> str:
            """A greeting prompt."""
            return "Hello, world!"

        manager = PromptManager()
        added = manager.add_prompt(fn=fn, description="A custom greeting")

        assert added.name == "fn"
        assert added.description == "A custom greeting"
        assert len(manager.list_prompts()) == 1

    def test_add_duplicate_prompt(self, caplog):
        """Test adding the same prompt twice."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager()
        first = manager.add_prompt(fn=fn)
        second = manager.add_prompt(fn=fn)

        assert first == second
        assert len(manager.list_prompts()) == 1
        assert "Prompt already exists: fn" in caplog.text

    def test_disable_warn_on_duplicate_prompts(self, caplog):
        """Test disabling warning on duplicate prompts."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager(warn_on_duplicate_prompts=False)
        first = manager.add_prompt(fn=fn)
        second = manager.add_prompt(fn=fn)

        assert first == second
        assert len(manager.list_prompts()) == 1
        assert "Prompt already exists" not in caplog.text

    def test_list_prompts(self):
        """Test listing all prompts."""

        def fn1() -> str:
            return "Hello, world!"

        def fn2() -> str:
            return "Goodbye, world!"

        manager = PromptManager()
        prompt1 = manager.add_prompt(fn=fn1)
        prompt2 = manager.add_prompt(fn=fn2)

        prompts = manager.list_prompts()
        assert len(prompts) == 2
        assert prompt1 in prompts
        assert prompt2 in prompts

    @pytest.mark.anyio
    async def test_render_prompt(self):
        """Test rendering a prompt."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager()
        manager.add_prompt(fn=fn)

        messages = await manager.render_prompt("fn")
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content.text == "Hello, world!"

    @pytest.mark.anyio
    async def test_render_prompt_with_args(self):
        """Test rendering a prompt with arguments."""

        def fn(name: str) -> str:
            return f"Hello, {name}!"

        manager = PromptManager()
        manager.add_prompt(fn=fn)

        messages = await manager.render_prompt("fn", {"name": "Alice"})
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content.text == "Hello, Alice!"

    @pytest.mark.anyio
    async def test_render_prompt_with_missing_args(self):
        """Test rendering a prompt with missing required arguments."""

        def fn(name: str) -> str:
            return f"Hello, {name}!"

        manager = PromptManager()
        manager.add_prompt(fn=fn)

        with pytest.raises(ValueError, match="Missing required arguments"):
            await manager.render_prompt("fn")

    @pytest.mark.anyio
    async def test_render_unknown_prompt(self):
        """Test rendering an unknown prompt."""

        manager = PromptManager()

        with pytest.raises(ValueError, match="Unknown prompt"):
            await manager.render_prompt("unknown")
