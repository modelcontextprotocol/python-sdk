"""Tests for URI utility functions."""

from mcp.server.fastmcp.uri_utils import (
    filter_by_uri_paths,
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


class TestFilterByUriPaths:
    """Test the URI paths filtering function."""

    def test_filter_no_paths(self):
        """Test that no paths returns all items."""
        items = ["item1", "item2", "item3"]
        result = filter_by_uri_paths(items, None, lambda x: x)
        assert result == items

    def test_filter_empty_paths(self):
        """Test that empty paths list returns all items."""
        items = ["item1", "item2", "item3"]
        result = filter_by_uri_paths(items, [], lambda x: x)
        assert result == items

    def test_filter_single_path(self):
        """Test filtering with a single path."""
        items = [f"{TOOL_SCHEME}/math/add", f"{TOOL_SCHEME}/math/subtract", f"{TOOL_SCHEME}/string/concat"]
        result = filter_by_uri_paths(items, [f"{TOOL_SCHEME}/math"], lambda x: x)
        assert len(result) == 2
        assert f"{TOOL_SCHEME}/math/add" in result
        assert f"{TOOL_SCHEME}/math/subtract" in result

    def test_filter_multiple_paths(self):
        """Test filtering with multiple paths."""
        items = [
            f"{TOOL_SCHEME}/math/add",
            f"{TOOL_SCHEME}/math/subtract",
            f"{TOOL_SCHEME}/string/concat",
            f"{PROMPT_SCHEME}/greet/hello",
        ]
        result = filter_by_uri_paths(items, [f"{TOOL_SCHEME}/math", f"{PROMPT_SCHEME}/greet"], lambda x: x)
        assert len(result) == 3
        assert f"{TOOL_SCHEME}/math/add" in result
        assert f"{TOOL_SCHEME}/math/subtract" in result
        assert f"{PROMPT_SCHEME}/greet/hello" in result
        assert f"{TOOL_SCHEME}/string/concat" not in result

    def test_filter_paths_without_slash(self):
        """Test that paths without trailing slash only match at boundaries."""
        items = [
            f"{TOOL_SCHEME}/math/add",
            f"{TOOL_SCHEME}/math/subtract",
            f"{TOOL_SCHEME}/string/concat",
            f"{TOOL_SCHEME}/mathematic",
        ]
        result = filter_by_uri_paths(items, [f"{TOOL_SCHEME}/math", f"{TOOL_SCHEME}/string"], lambda x: x)
        assert len(result) == 3
        assert f"{TOOL_SCHEME}/math/add" in result
        assert f"{TOOL_SCHEME}/math/subtract" in result
        assert f"{TOOL_SCHEME}/string/concat" in result
        assert f"{TOOL_SCHEME}/mathematic" not in result

    def test_filter_with_trailing_slashes(self):
        """Test filtering when paths have trailing slashes."""
        items = [
            f"{PROMPT_SCHEME}/greet/hello",
            f"{PROMPT_SCHEME}/greet/goodbye",
            f"{PROMPT_SCHEME}/chat/start",
        ]
        result = filter_by_uri_paths(items, [f"{PROMPT_SCHEME}/greet/", f"{PROMPT_SCHEME}/chat/"], lambda x: x)
        assert len(result) == 3
        assert all(item in result for item in items)

    def test_filter_overlapping_paths(self):
        """Test filtering with overlapping paths."""
        items = [
            f"{TOOL_SCHEME}/math",
            f"{TOOL_SCHEME}/math/add",
            f"{TOOL_SCHEME}/math/advanced/multiply",
        ]
        result = filter_by_uri_paths(items, [f"{TOOL_SCHEME}/math", f"{TOOL_SCHEME}/math/advanced"], lambda x: x)
        assert len(result) == 3  # All items match
        assert all(item in result for item in items)

    def test_filter_no_matches(self):
        """Test filtering when no items match any path."""
        items = [f"{TOOL_SCHEME}/math/add", f"{TOOL_SCHEME}/math/subtract"]
        result = filter_by_uri_paths(items, [f"{TOOL_SCHEME}/string", f"{PROMPT_SCHEME}/greet"], lambda x: x)
        assert result == []

    def test_filter_with_objects(self):
        """Test filtering objects using a URI getter function."""

        class MockResource:
            def __init__(self, uri):
                self.uri = uri

        resources = [
            MockResource(f"{TOOL_SCHEME}/math/add"),
            MockResource(f"{TOOL_SCHEME}/string/concat"),
            MockResource(f"{PROMPT_SCHEME}/greet/hello"),
        ]

        result = filter_by_uri_paths(resources, [f"{TOOL_SCHEME}/math", f"{PROMPT_SCHEME}/greet"], lambda r: r.uri)
        assert len(result) == 2
        assert result[0].uri == f"{TOOL_SCHEME}/math/add"
        assert result[1].uri == f"{PROMPT_SCHEME}/greet/hello"

    def test_filter_case_sensitive(self):
        """Test that filtering is case sensitive."""
        items = [f"{TOOL_SCHEME}/Math/add", f"{TOOL_SCHEME}/math/add"]
        result = filter_by_uri_paths(items, [f"{TOOL_SCHEME}/math"], lambda x: x)
        assert len(result) == 1
        assert f"{TOOL_SCHEME}/math/add" in result

    def test_filter_exact_path_match(self):
        """Test that exact path matches work correctly."""
        items = [f"{TOOL_SCHEME}/test", f"{TOOL_SCHEME}/test/sub", f"{TOOL_SCHEME}/testing"]
        result = filter_by_uri_paths(items, [f"{TOOL_SCHEME}/test"], lambda x: x)
        assert len(result) == 2
        assert f"{TOOL_SCHEME}/test" in result
        assert f"{TOOL_SCHEME}/test/sub" in result
        assert f"{TOOL_SCHEME}/testing" not in result
