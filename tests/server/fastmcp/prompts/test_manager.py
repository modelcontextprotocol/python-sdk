import pytest

from mcp.server.fastmcp.prompts.base import Prompt, TextContent, UserMessage
from mcp.server.fastmcp.prompts.manager import PromptManager


class TestPromptManager:
    def test_add_prompt(self):
        """Test adding a prompt to the manager."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager()
        added = manager.add_prompt(fn)
        assert isinstance(added, Prompt)
        assert added.name == "fn"
        assert manager.get_prompt("fn") == added

    def test_add_prompt_object(self):
        """Test adding a Prompt object directly."""

        def fn() -> str:
            return "Hello, world!"

        prompt = Prompt.from_function(fn, name="test_prompt", description="Test prompt")
        manager = PromptManager()
        added = manager.add_prompt(prompt)
        assert added == prompt
        assert manager.get_prompt("test_prompt") == prompt

    def test_add_prompt_object_ignores_name_and_description(self):
        """Test that name and description args are ignored when adding a Prompt object."""

        def fn() -> str:
            return "Hello, world!"

        prompt = Prompt.from_function(
            fn, name="original_name", description="Original description"
        )
        manager = PromptManager()
        # These should be ignored
        added = manager.add_prompt(
            prompt, name="ignored_name", description="ignored_description"
        )
        assert added.name == "original_name"
        assert added.description == "Original description"

    def test_add_duplicate_prompt(self, caplog):
        """Test adding the same prompt twice."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager()
        first = manager.add_prompt(fn)
        second = manager.add_prompt(fn)
        assert first == second
        assert "Prompt already exists" in caplog.text

    def test_disable_warn_on_duplicate_prompts(self, caplog):
        """Test disabling warning on duplicate prompts."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager(warn_on_duplicate_prompts=False)
        first = manager.add_prompt(fn)
        second = manager.add_prompt(fn)
        assert first == second
        assert "Prompt already exists" not in caplog.text

    def test_list_prompts(self):
        """Test listing all prompts."""

        def fn1() -> str:
            return "Hello, world!"

        def fn2() -> str:
            return "Goodbye, world!"

        manager = PromptManager()
        prompt1 = manager.add_prompt(fn1)
        prompt2 = manager.add_prompt(fn2)
        prompts = manager.list_prompts()
        assert len(prompts) == 2
        assert prompts == [prompt1, prompt2]

    @pytest.mark.anyio
    async def test_render_prompt(self):
        """Test rendering a prompt."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager()
        manager.add_prompt(fn)
        messages = await manager.render_prompt("fn")
        assert messages == [
            UserMessage(content=TextContent(type="text", text="Hello, world!"))
        ]

    @pytest.mark.anyio
    async def test_render_prompt_with_args(self):
        """Test rendering a prompt with arguments."""

        def fn(name: str) -> str:
            return f"Hello, {name}!"

        manager = PromptManager()
        manager.add_prompt(fn)
        messages = await manager.render_prompt("fn", arguments={"name": "World"})
        assert messages == [
            UserMessage(content=TextContent(type="text", text="Hello, World!"))
        ]

    @pytest.mark.anyio
    async def test_render_unknown_prompt(self):
        """Test rendering a non-existent prompt."""
        manager = PromptManager()
        with pytest.raises(ValueError, match="Unknown prompt: unknown"):
            await manager.render_prompt("unknown")

    @pytest.mark.anyio
    async def test_render_prompt_with_missing_args(self):
        """Test rendering a prompt with missing required arguments."""

        def fn(name: str) -> str:
            return f"Hello, {name}!"

        manager = PromptManager()
        manager.add_prompt(fn)
        with pytest.raises(ValueError, match="Missing required arguments"):
            await manager.render_prompt("fn")
