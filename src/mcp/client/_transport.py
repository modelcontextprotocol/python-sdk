import sys

import mcp_client.client._transport as _implementation
from mcp_client.client._transport import (
    ReadStream as ReadStream,
)
from mcp_client.client._transport import (
    Transport as Transport,
)
from mcp_client.client._transport import (
    TransportStreams as TransportStreams,
)
from mcp_client.client._transport import (
    WriteStream as WriteStream,
)

sys.modules[__name__] = _implementation
