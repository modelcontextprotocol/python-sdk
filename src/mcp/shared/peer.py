import sys

import mcp_client.shared.peer as _implementation
from mcp_client.shared.peer import (
    ClientPeer as ClientPeer,
)
from mcp_client.shared.peer import (
    Meta as Meta,
)
from mcp_client.shared.peer import (
    dump_params as dump_params,
)

sys.modules[__name__] = _implementation
