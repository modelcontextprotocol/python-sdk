import sys

import mcp_client.client._memory as _implementation
from mcp_client.client._memory import (
    SERVER_SHUTDOWN_GRACE as SERVER_SHUTDOWN_GRACE,
)
from mcp_client.client._memory import (
    InMemoryTransport as InMemoryTransport,
)

sys.modules[__name__] = _implementation
