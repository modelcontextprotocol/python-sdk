import sys

import mcp_client.shared.memory as _implementation
from mcp_client.shared.memory import (
    MessageStream as MessageStream,
)
from mcp_client.shared.memory import (
    create_client_server_memory_streams as create_client_server_memory_streams,
)

sys.modules[__name__] = _implementation
