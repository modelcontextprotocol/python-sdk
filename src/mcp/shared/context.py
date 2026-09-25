import sys

import mcp_client.shared.context as _implementation
from mcp_client.shared.context import (
    BaseContext as BaseContext,
)
from mcp_client.shared.context import (
    TransportT as TransportT,
)

sys.modules[__name__] = _implementation
