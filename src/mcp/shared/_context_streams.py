import sys

import mcp_client.shared._context_streams as _implementation
from mcp_client.shared._context_streams import (
    ContextReceiveStream as ContextReceiveStream,
)
from mcp_client.shared._context_streams import (
    ContextSendStream as ContextSendStream,
)
from mcp_client.shared._context_streams import (
    T as T,
)
from mcp_client.shared._context_streams import (
    _Envelope as _Envelope,
)
from mcp_client.shared._context_streams import (
    create_context_streams as create_context_streams,
)

sys.modules[__name__] = _implementation
