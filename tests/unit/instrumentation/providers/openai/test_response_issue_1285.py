"""
Regression test for issue #1285:
'NoneType' object has no attribute '__dict__' in get_response_tool_web/file_search_attributes

When OpenAI Agents SDK tools have optional fields (user_location, filters, ranking_options)
set to None, hasattr() returns True but .__dict__ access crashes.
"""

import pytest
from unittest.mock import MagicMock

from agentops.instrumentation.providers.openai.attributes.response import (
    get_response_tool_web_search_attributes,
    get_response_tool_file_search_attributes,
)


class MockUserLocation:
    """Mock user_location object with a __dict__ attribute."""
    def __init__(self):
        self.type = "approximate"
        self.country = "US"


class MockRankingOptions:
    """Mock ranking_options object with a __dict__ attribute."""
    def __init__(self):
        self.score_threshold = 0.5


class MockFilters:
    """Mock filters object with a __dict__ attribute."""
    def __init__(self):
        self.type = "and"
        self.filters = []


class TestIssue1285:
    """Test that None optional fields don't crash attribute extraction."""

    def test_web_search_tool_with_none_user_location(self):
        """user_location=None should not cause AttributeError."""
        tool = MagicMock()
        tool.search_context_size = 1024
        tool.user_location = None  # This is the bug: hasattr returns True, but .__dict__ crashes

        # Should not raise AttributeError
        result = get_response_tool_web_search_attributes(tool, index=0)
        assert isinstance(result, dict)

    def test_web_search_tool_with_valid_user_location(self):
        """user_location with a real object should still work."""
        tool = MagicMock()
        tool.search_context_size = 1024
        tool.user_location = MockUserLocation()
        tool.user_location.__dict__ = {"type": "approximate", "country": "US"}

        result = get_response_tool_web_search_attributes(tool, index=0)
        assert isinstance(result, dict)

    def test_file_search_tool_with_none_filters(self):
        """filters=None should not cause AttributeError."""
        tool = MagicMock()
        tool.vector_store_ids = ["vs_123"]
        tool.filters = None  # Bug: hasattr returns True, .__dict__ crashes
        tool.max_num_results = 5
        tool.ranking_options = None  # Bug: same issue

        result = get_response_tool_file_search_attributes(tool, index=0)
        assert isinstance(result, dict)

    def test_file_search_tool_with_none_ranking_options(self):
        """ranking_options=None should not cause AttributeError."""
        tool = MagicMock()
        tool.vector_store_ids = ["vs_123"]
        tool.filters = MockFilters()
        tool.max_num_results = 5
        tool.ranking_options = None

        result = get_response_tool_file_search_attributes(tool, index=0)
        assert isinstance(result, dict)

    def test_file_search_tool_with_valid_fields(self):
        """All valid fields should still work correctly."""
        tool = MagicMock()
        tool.vector_store_ids = ["vs_123"]
        tool.filters = MockFilters()
        tool.filters.__dict__ = {"type": "and", "filters": []}
        tool.max_num_results = 5
        tool.ranking_options = MockRankingOptions()
        tool.ranking_options.__dict__ = {"score_threshold": 0.5}

        result = get_response_tool_file_search_attributes(tool, index=0)
        assert isinstance(result, dict)
