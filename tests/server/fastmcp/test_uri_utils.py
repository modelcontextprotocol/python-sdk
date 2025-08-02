"""Tests for URI utility functions."""

from mcp.server.fastmcp.uri_utils import (
    filter_by_prefix,
    normalize_to_prompt_uri,
    normalize_to_tool_uri,
    normalize_to_uri,
)
from mcp.types import PROMPT_SCHEME, TOOL_SCHEME


class TestNormalizeToUri:
    """Test the generic normalize_to_uri function."""

    def test_normalize_name_to_uri(self):
        """Test converting a name to URI."""
        result = normalize_to_uri("test_name", TOOL_SCHEME)
        assert result == f"{TOOL_SCHEME}/test_name"

    def test_normalize_already_uri(self):
        """Test that URIs are returned unchanged."""
        uri = f"{TOOL_SCHEME}/existing_uri"
        result = normalize_to_uri(uri, TOOL_SCHEME)
        assert result == uri

    def test_normalize_with_different_scheme(self):
        """Test normalizing with different schemes."""
        result = normalize_to_uri("test", PROMPT_SCHEME)
        assert result == f"{PROMPT_SCHEME}/test"

    def test_normalize_empty_name(self):
        """Test normalizing empty string."""
        result = normalize_to_uri("", TOOL_SCHEME)
        assert result == f"{TOOL_SCHEME}/"

    def test_normalize_special_characters(self):
        """Test normalizing names with special characters."""
        result = normalize_to_uri("test-name_123", TOOL_SCHEME)
        assert result == f"{TOOL_SCHEME}/test-name_123"


class TestNormalizeToToolUri:
    """Test the tool-specific URI normalization."""

    def test_normalize_tool_name(self):
        """Test converting tool name to URI."""
        result = normalize_to_tool_uri("calculator")
        assert result == f"{TOOL_SCHEME}/calculator"

    def test_normalize_existing_tool_uri(self):
        """Test that tool URIs are returned unchanged."""
        uri = f"{TOOL_SCHEME}/existing_tool"
        result = normalize_to_tool_uri(uri)
        assert result == uri

    def test_normalize_tool_with_path(self):
        """Test normalizing tool names that look like paths."""
        result = normalize_to_tool_uri("math/calculator")
        assert result == f"{TOOL_SCHEME}/math/calculator"


class TestNormalizeToPromptUri:
    """Test the prompt-specific URI normalization."""

    def test_normalize_prompt_name(self):
        """Test converting prompt name to URI."""
        result = normalize_to_prompt_uri("greeting")
        assert result == f"{PROMPT_SCHEME}/greeting"

    def test_normalize_existing_prompt_uri(self):
        """Test that prompt URIs are returned unchanged."""
        uri = f"{PROMPT_SCHEME}/existing_prompt"
        result = normalize_to_prompt_uri(uri)
        assert result == uri

    def test_normalize_prompt_with_path(self):
        """Test normalizing prompt names that look like paths."""
        result = normalize_to_prompt_uri("templates/greeting")
        assert result == f"{PROMPT_SCHEME}/templates/greeting"


class TestFilterByPrefix:
    """Test the prefix filtering function."""

    def test_filter_no_prefix(self):
        """Test that no prefix returns all items."""
        items = ["item1", "item2", "item3"]
        result = filter_by_prefix(items, None, lambda x: x)
        assert result == items

    def test_filter_with_prefix(self):
        """Test filtering with a prefix."""
        items = [f"{TOOL_SCHEME}/math/add", f"{TOOL_SCHEME}/math/subtract", f"{TOOL_SCHEME}/string/concat"]
        result = filter_by_prefix(items, f"{TOOL_SCHEME}/math", lambda x: x)
        assert len(result) == 2
        assert f"{TOOL_SCHEME}/math/add" in result
        assert f"{TOOL_SCHEME}/math/subtract" in result

    def test_filter_prefix_without_slash(self):
        """Test that prefix without trailing slash only matches at boundaries."""
        items = [
            f"{TOOL_SCHEME}/math/add",
            f"{TOOL_SCHEME}/math/subtract",
            f"{TOOL_SCHEME}/string/concat",
            f"{TOOL_SCHEME}/mathematic",
        ]
        result = filter_by_prefix(items, f"{TOOL_SCHEME}/math", lambda x: x)
        assert len(result) == 2  # Matches because next char is '/'
        assert f"{TOOL_SCHEME}/math/add" in result
        assert f"{TOOL_SCHEME}/math/subtract" in result
        assert f"{TOOL_SCHEME}/mathematic" not in result  # Doesn't match because next char is 'e'

        # With trailing slash also matches
        result_with_slash = filter_by_prefix(items, f"{TOOL_SCHEME}/math/", lambda x: x)
        assert len(result_with_slash) == 2
        assert result_with_slash == result

    def test_filter_with_trailing_slash(self):
        """Test filtering when prefix already has trailing slash."""
        items = [f"{PROMPT_SCHEME}/greet/hello", f"{PROMPT_SCHEME}/greet/goodbye", f"{PROMPT_SCHEME}/chat/start"]
        result = filter_by_prefix(items, f"{PROMPT_SCHEME}/greet/", lambda x: x)
        assert len(result) == 2
        assert f"{PROMPT_SCHEME}/greet/hello" in result
        assert f"{PROMPT_SCHEME}/greet/goodbye" in result

    def test_filter_empty_list(self):
        """Test filtering empty list."""
        items = []
        result = filter_by_prefix(items, "any://prefix", lambda x: x)
        assert result == []

    def test_filter_no_matches(self):
        """Test filtering when no items match."""
        items = [f"{TOOL_SCHEME}/math/add", f"{TOOL_SCHEME}/math/subtract"]
        result = filter_by_prefix(items, f"{TOOL_SCHEME}/string", lambda x: x)
        assert result == []

    def test_filter_with_objects(self):
        """Test filtering objects using a URI getter function."""

        class MockTool:
            def __init__(self, uri):
                self.uri = uri

        tools = [
            MockTool(f"{TOOL_SCHEME}/math/add"),
            MockTool(f"{TOOL_SCHEME}/math/multiply"),
            MockTool(f"{TOOL_SCHEME}/string/concat"),
        ]

        result = filter_by_prefix(tools, f"{TOOL_SCHEME}/math", lambda t: t.uri)
        assert len(result) == 2
        assert result[0].uri == f"{TOOL_SCHEME}/math/add"
        assert result[1].uri == f"{TOOL_SCHEME}/math/multiply"

    def test_filter_case_sensitive(self):
        """Test that filtering is case sensitive."""
        items = [f"{TOOL_SCHEME}/Math/add", f"{TOOL_SCHEME}/math/add"]
        result = filter_by_prefix(items, f"{TOOL_SCHEME}/math", lambda x: x)
        assert len(result) == 1
        assert f"{TOOL_SCHEME}/math/add" in result

    def test_filter_exact_prefix_match(self):
        """Test that exact prefix matches work correctly."""
        items = [f"{TOOL_SCHEME}/test", f"{TOOL_SCHEME}/test/sub", f"{TOOL_SCHEME}/testing"]
        result = filter_by_prefix(items, f"{TOOL_SCHEME}/test", lambda x: x)
        # Should match "tool:/test" (exact) and "tool:/test/sub" but not "tool:/testing"
        assert len(result) == 2
        assert f"{TOOL_SCHEME}/test" in result
        assert f"{TOOL_SCHEME}/test/sub" in result
        assert f"{TOOL_SCHEME}/testing" not in result

    def test_filter_root_prefix(self):
        """Test filtering with just the scheme as prefix."""
        items = [f"{TOOL_SCHEME}/add", f"{TOOL_SCHEME}/subtract", f"{PROMPT_SCHEME}/greet"]
        result = filter_by_prefix(items, f"{TOOL_SCHEME}/", lambda x: x)
        assert len(result) == 2
        assert f"{TOOL_SCHEME}/add" in result
        assert f"{TOOL_SCHEME}/subtract" in result
        assert f"{PROMPT_SCHEME}/greet" not in result
