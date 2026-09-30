import sys
from typing import Any

import mcp_client.client.client as _implementation
from mcp_client.client.client import (
    _T as _T,
)
from mcp_client.client.client import (
    Client as Client,
)
from mcp_client.client.client import (
    ConnectMode as ConnectMode,
)
from mcp_client.client.client import (
    _CacheableT as _CacheableT,
)
from mcp_client.client.client import (
    _connect_transport as _connect_transport,
)
from mcp_client.client.client import (
    _connected as _connected,
)
from mcp_client.client.client import (
    _Connector as _Connector,
)
from mcp_client.client.client import (
    _evicting_message_handler as _evicting_message_handler,
)
from mcp_client.client.client import (
    _fold_extensions as _fold_extensions,
)
from mcp_client.client.client import (
    _FoldedExtensions as _FoldedExtensions,
)
from mcp_client.client.client import (
    _ResultT as _ResultT,
)
from mcp_client.client.client import (
    _strip_userinfo as _strip_userinfo,
)
from mcp_client.client.client import (
    _synthesize_discover as _synthesize_discover,
)
from mcp_client.client.client import (
    logger as logger,
)

from mcp.server import Server
from mcp.server.mcpserver import MCPServer

# Keep runtime annotations resolvable through the full SDK's existing import path.
_implementation._InProcessServer = Server[Any] | MCPServer
sys.modules[__name__] = _implementation
