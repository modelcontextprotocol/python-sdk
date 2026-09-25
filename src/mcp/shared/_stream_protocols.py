import sys

import mcp_client.shared._stream_protocols as _implementation
from mcp_client.shared._stream_protocols import (
    ReadStream as ReadStream,
)
from mcp_client.shared._stream_protocols import (
    T_co as T_co,
)
from mcp_client.shared._stream_protocols import (
    T_contra as T_contra,
)
from mcp_client.shared._stream_protocols import (
    WriteStream as WriteStream,
)

sys.modules[__name__] = _implementation
