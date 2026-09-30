import sys

import mcp_client.shared._compat as _implementation
from mcp_client.shared._compat import (
    resync_tracer as resync_tracer,
)

sys.modules[__name__] = _implementation
