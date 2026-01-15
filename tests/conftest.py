import os

import pytest

os.environ["NO_PROXY"] = "127.0.0.1"


@pytest.fixture
def anyio_backend():
    return "asyncio"
