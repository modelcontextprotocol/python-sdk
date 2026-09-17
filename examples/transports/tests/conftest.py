from collections.abc import AsyncIterator

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
async def grpc_event_loop(anyio_backend: str) -> AsyncIterator[None]:
    """Keep gRPC's process-wide completion queue on one loop, including late connectivity callbacks."""
    yield
