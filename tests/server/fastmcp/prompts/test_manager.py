import pytest

from mcp.server.fastmcp.prompts.base import Prompt, TextContent, UserMessage
from mcp.server.fastmcp.prompts.manager import PromptManager
from mcp.types import PROMPT_SCHEME


class TestPromptManager:
    def test_add_prompt(self):
        """Test adding a prompt to the manager."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager()
        prompt = Prompt.from_function(fn)
        added = manager.add_prompt(prompt)
        assert added == prompt
        assert manager.get_prompt("fn") == prompt

    def test_add_duplicate_prompt(self, caplog):
        """Test adding the same prompt twice."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager()
        prompt = Prompt.from_function(fn)
        first = manager.add_prompt(prompt)
        second = manager.add_prompt(prompt)
        assert first == second
        assert "Prompt already exists" in caplog.text

    def test_disable_warn_on_duplicate_prompts(self, caplog):
        """Test disabling warning on duplicate prompts."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager(warn_on_duplicate_prompts=False)
        prompt = Prompt.from_function(fn)
        first = manager.add_prompt(prompt)
        second = manager.add_prompt(prompt)
        assert first == second
        assert "Prompt already exists" not in caplog.text

    def test_list_prompts(self):
        """Test listing all prompts."""

        def fn1() -> str:
            return "Hello, world!"

        def fn2() -> str:
            return "Goodbye, world!"

        manager = PromptManager()
        prompt1 = Prompt.from_function(fn1)
        prompt2 = Prompt.from_function(fn2)
        manager.add_prompt(prompt1)
        manager.add_prompt(prompt2)
        prompts = manager.list_prompts()
        assert len(prompts) == 2
        assert prompts == [prompt1, prompt2]

    def test_list_prompts_with_prefix(self):
        """Test listing prompts with prefix filtering."""

        def greeting_hello() -> str:
            return "Hello!"

        def greeting_goodbye() -> str:
            return "Goodbye!"

        def question_name() -> str:
            return "What's your name?"

        def question_age() -> str:
            return "How old are you?"

        manager = PromptManager()

        # Create prompts with custom URIs
        hello_prompt = Prompt.from_function(greeting_hello)
        hello_prompt.uri = f"{PROMPT_SCHEME}/greeting/hello"

        goodbye_prompt = Prompt.from_function(greeting_goodbye)
        goodbye_prompt.uri = f"{PROMPT_SCHEME}/greeting/goodbye"

        name_prompt = Prompt.from_function(question_name)
        name_prompt.uri = f"{PROMPT_SCHEME}/question/name"

        age_prompt = Prompt.from_function(question_age)
        age_prompt.uri = f"{PROMPT_SCHEME}/question/age"

        # Add prompts directly to manager's internal storage
        manager._prompts = {
            str(hello_prompt.uri): hello_prompt,
            str(goodbye_prompt.uri): goodbye_prompt,
            str(name_prompt.uri): name_prompt,
            str(age_prompt.uri): age_prompt,
        }

        # Test listing all prompts
        all_prompts = manager.list_prompts()
        assert len(all_prompts) == 4

        # Test uri_paths filtering - greeting prompts
        greeting_prompts = manager.list_prompts(uri_paths=[f"{PROMPT_SCHEME}/greeting/"])
        assert len(greeting_prompts) == 2
        assert all(str(p.uri).startswith(f"{PROMPT_SCHEME}/greeting/") for p in greeting_prompts)
        assert hello_prompt in greeting_prompts
        assert goodbye_prompt in greeting_prompts

        # Test uri_paths filtering - question prompts
        question_prompts = manager.list_prompts(uri_paths=[f"{PROMPT_SCHEME}/question/"])
        assert len(question_prompts) == 2
        assert all(str(p.uri).startswith(f"{PROMPT_SCHEME}/question/") for p in question_prompts)
        assert name_prompt in question_prompts
        assert age_prompt in question_prompts

        # Test exact URI match
        hello_prompts = manager.list_prompts(uri_paths=[f"{PROMPT_SCHEME}/greeting/hello"])
        assert len(hello_prompts) == 1
        assert hello_prompts[0] == hello_prompt

        # Test partial prefix doesn't match
        no_partial = manager.list_prompts(uri_paths=[f"{PROMPT_SCHEME}/greeting/h"])
        assert len(no_partial) == 0  # Won't match because next char is 'e' not a separator

        # Test no matches
        no_matches = manager.list_prompts(uri_paths=[f"{PROMPT_SCHEME}/nonexistent"])
        assert len(no_matches) == 0

        # Test with trailing slash
        greeting_prompts_slash = manager.list_prompts(uri_paths=[f"{PROMPT_SCHEME}/greeting/"])
        assert len(greeting_prompts_slash) == 2
        assert greeting_prompts_slash == greeting_prompts

        # Test multiple uri_paths
        greeting_and_question = manager.list_prompts(
            uri_paths=[f"{PROMPT_SCHEME}/greeting/", f"{PROMPT_SCHEME}/question/"]
        )
        assert len(greeting_and_question) == 4
        assert all(p in greeting_and_question for p in all_prompts)

    @pytest.mark.anyio
    async def test_render_prompt(self):
        """Test rendering a prompt."""

        def fn() -> str:
            return "Hello, world!"

        manager = PromptManager()
        prompt = Prompt.from_function(fn)
        manager.add_prompt(prompt)
        messages = await manager.render_prompt("fn")
        assert messages == [UserMessage(content=TextContent(type="text", text="Hello, world!"))]

    @pytest.mark.anyio
    async def test_render_prompt_with_args(self):
        """Test rendering a prompt with arguments."""

        def fn(name: str) -> str:
            return f"Hello, {name}!"

        manager = PromptManager()
        prompt = Prompt.from_function(fn)
        manager.add_prompt(prompt)
        messages = await manager.render_prompt("fn", arguments={"name": "World"})
        assert messages == [UserMessage(content=TextContent(type="text", text="Hello, World!"))]

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
        prompt = Prompt.from_function(fn)
        manager.add_prompt(prompt)
        with pytest.raises(ValueError, match="Missing required arguments"):
            await manager.render_prompt("fn")

    def test_get_prompt_by_uri(self):
        """Test getting prompts by their URI."""

        def greeting() -> str:
            return "Hello!"

        def custom_prompt() -> str:
            return "Custom message"

        manager = PromptManager()

        # Add prompt with default URI
        manager.add_prompt(Prompt.from_function(greeting))

        # Add prompt with custom URI
        custom = Prompt.from_function(custom_prompt)
        custom.uri = f"{PROMPT_SCHEME}/custom/messages/welcome"
        manager._prompts[str(custom.uri)] = custom

        # Get by name
        prompt = manager.get_prompt("greeting")
        assert prompt is not None
        assert prompt.name == "greeting"

        # Get by default URI
        prompt_by_uri = manager.get_prompt(f"{PROMPT_SCHEME}/greeting")
        assert prompt_by_uri is not None
        assert prompt_by_uri.name == "greeting"
        assert prompt_by_uri == prompt

        # Get by custom URI
        custom_by_uri = manager.get_prompt(f"{PROMPT_SCHEME}/custom/messages/welcome")
        assert custom_by_uri is not None
        assert custom_by_uri == custom

    @pytest.mark.anyio
    async def test_render_prompt_by_uri(self):
        """Test rendering prompts by their URI."""

        def welcome(name: str) -> str:
            return f"Welcome, {name}!"

        def farewell(name: str) -> str:
            return f"Goodbye, {name}!"

        manager = PromptManager()

        # Add prompt with default URI
        manager.add_prompt(Prompt.from_function(welcome))

        # Add prompt with custom URI
        farewell_prompt = Prompt.from_function(farewell)
        farewell_prompt.uri = f"{PROMPT_SCHEME}/custom/farewell"
        manager._prompts[str(farewell_prompt.uri)] = farewell_prompt

        # Render by default URI
        messages = await manager.render_prompt(f"{PROMPT_SCHEME}/welcome", arguments={"name": "Alice"})
        assert messages == [UserMessage(content=TextContent(type="text", text="Welcome, Alice!"))]

        # Render by custom URI
        messages = await manager.render_prompt(f"{PROMPT_SCHEME}/custom/farewell", arguments={"name": "Bob"})
        assert messages == [UserMessage(content=TextContent(type="text", text="Goodbye, Bob!"))]

        # Should still work with name
        messages = await manager.render_prompt("welcome", arguments={"name": "Charlie"})
        assert messages == [UserMessage(content=TextContent(type="text", text="Welcome, Charlie!"))]
