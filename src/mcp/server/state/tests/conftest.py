# pytest -n 0 -o log_cli=true -o log_cli_level=INFO src\mcp\server\state\tests

import pytest

@pytest.fixture
def anyio_backend():
    # Run tests on asyncio only (no trio dependency required)
    return "asyncio"
