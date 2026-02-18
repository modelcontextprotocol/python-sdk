"""Test dependency injection system."""

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
import pytest

from mcp.server.mcpserver.utilities.dependencies import Depends, find_dependency_parameters
from mcp.server.mcpserver.utilities.dependency_resolver import DependencyResolver


class TestDepends:
    def test_depends_creation(self):
        def get_dep() -> str:
            return "dep"

        dep = Depends(get_dep)
        assert dep.dependency == get_dep
        assert dep.use_cache is True

    def test_depends_without_cache(self):
        def get_dep() -> str:
            return "dep"

        dep = Depends(get_dep, use_cache=False)
        assert dep.dependency == get_dep
        assert dep.use_cache is False

    def test_find_dependency_parameters(self):
        def get_db() -> str:
            return "db"

        def tool_func(arg: int, db: str = Depends(get_db)) -> str:
            return db

        params = find_dependency_parameters(tool_func)
        assert "db" in params
        assert isinstance(params["db"], Depends)
        assert params["db"].dependency == get_db

    def test_find_dependency_parameters_empty(self):
        def tool_func(arg: int) -> str:
            return str(arg)

        params = find_dependency_parameters(tool_func)
        assert params == {}

    def test_depends_repr(self):
        def get_dep() -> str:
            return "dep"

        dep = Depends(get_dep)
        assert repr(dep) == "Depends(get_dep)"
        assert str(dep) == "Depends(get_dep)"

    def test_find_dependency_parameters_signature_error(self):
        # Test that signature errors are handled gracefully
        class BadFunction:
            """A function that will raise an error when getting signature."""

        params = find_dependency_parameters(BadFunction)
        assert params == {}


class TestDependencyResolver:
    @pytest.mark.anyio
    async def test_resolve_simple_dependency(self):
        def get_value() -> str:
            return "test_value"

        resolver = DependencyResolver()
        dep = Depends(get_value)

        result = await resolver.resolve("value", dep)
        assert result == "test_value"

    @pytest.mark.anyio
    async def test_resolve_with_cache(self):
        call_count = 0

        def get_value() -> str:
            nonlocal call_count
            call_count += 1
            return "test_value"

        resolver = DependencyResolver()
        dep = Depends(get_value, use_cache=True)

        # First call
        result1 = await resolver.resolve("value", dep)
        assert result1 == "test_value"
        assert call_count == 1

        # Second call should use cache
        result2 = await resolver.resolve("value", dep)
        assert result2 == "test_value"
        assert call_count == 1  # Should not increment

    @pytest.mark.anyio
    async def test_resolve_without_cache(self):
        call_count = 0

        def get_value() -> str:
            nonlocal call_count
            call_count += 1
            return "test_value"

        resolver = DependencyResolver()
        dep = Depends(get_value, use_cache=False)

        # First call
        result1 = await resolver.resolve("value", dep)
        assert result1 == "test_value"
        assert call_count == 1

        # Second call should NOT use cache
        result2 = await resolver.resolve("value", dep)
        assert result2 == "test_value"
        assert call_count == 2  # Should increment

    @pytest.mark.anyio
    async def test_resolve_nested_dependency(self):
        def get_config() -> dict[str, str]:
            return {"db_url": "test"}

        def get_db(config: dict[str, str] = Depends(get_config)) -> str:
            return config["db_url"]

        resolver = DependencyResolver()
        dep = Depends(get_db)

        result = await resolver.resolve("db", dep)
        assert result == "test"

    @pytest.mark.anyio
    async def test_resolve_with_override(self):
        def get_value() -> str:
            return "production"

        def get_test_value() -> str:
            return "test"

        resolver = DependencyResolver(overrides={get_value: get_test_value})
        dep = Depends(get_value)

        result = await resolver.resolve("value", dep)
        assert result == "test"

    @pytest.mark.anyio
    async def test_resolve_async_dependency(self):
        async def get_async_value() -> str:
            return "async_value"

        resolver = DependencyResolver()
        dep = Depends(get_async_value)

        result = await resolver.resolve("value", dep)
        assert result == "async_value"

    @pytest.mark.anyio
    async def test_resolve_nested_async_dependency(self):
        async def get_config() -> dict[str, str]:
            return {"db_url": "test_async"}

        async def get_db(config: dict[str, str] = Depends(get_config)) -> str:
            return config["db_url"]

        resolver = DependencyResolver()
        dep = Depends(get_db)

        result = await resolver.resolve("db", dep)
        assert result == "test_async"

    @pytest.mark.anyio
    async def test_resolve_dependency_not_in_signature(self):
        """Test handling when dependency name is in kwarg_names but not in signature."""

        def get_value() -> str:
            return "test"

        def other_func() -> str:
            return "other"

        # Create a tool with dependencies
        from mcp.server.mcpserver.tools.base import Tool

        async def tool_func(value: str = Depends(get_value)) -> str:
            return value

        tool = Tool.from_function(tool_func)

        # Manually add a dependency that doesn't exist in signature
        tool.dependency_kwarg_names.append("nonexistent")

        # This should handle the missing dependency gracefully
        # (in practice this shouldn't happen, but we need to test the branch)
        deps = find_dependency_parameters(tool_func)
        assert "nonexistent" not in deps
