import sys

import mcp_client.shared.transport_context as _implementation
from mcp_client.shared.transport_context import (
    TransportContext as TransportContext,
)

sys.modules[__name__] = _implementation
