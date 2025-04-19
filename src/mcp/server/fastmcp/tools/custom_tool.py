from typing import Any, Callable

from mcp.server.fastmcp.tools.base import Tool


class CustomTool(Tool):
    """Custom tool with post-processing capabilities."""

    post_process_fn: Callable[[Any, str, dict[str, Any]], Any] = None

    @classmethod
    def set_post_processor(cls, fn: Callable[[Any, str, dict[str, Any]], Any]) -> None:
        """Set the post-processing function."""
        cls.post_process_fn = fn

    @classmethod
    def post_process_result(cls, result: Any, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Post-process the result using the configured function."""
        if cls.post_process_fn:
            return cls.post_process_fn(result, tool_name, arguments)
        return result
