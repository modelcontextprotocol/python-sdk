import sys

import mcp_client.client.sse as _implementation
from mcp_client.client.sse import (
    _extract_session_id_from_endpoint as _extract_session_id_from_endpoint,
)
from mcp_client.client.sse import (
    logger as logger,
)
from mcp_client.client.sse import (
    remove_request_params as remove_request_params,
)
from mcp_client.client.sse import (
    sse_client as sse_client,
)

sys.modules[__name__] = _implementation
