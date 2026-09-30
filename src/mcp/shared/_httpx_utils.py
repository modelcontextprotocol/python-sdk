import sys

import mcp_client.shared._httpx_utils as _implementation
from mcp_client.shared._httpx_utils import (
    _AUTH_REDIRECT_LIMIT as _AUTH_REDIRECT_LIMIT,
)
from mcp_client.shared._httpx_utils import (
    _SSE_HEADERS as _SSE_HEADERS,
)
from mcp_client.shared._httpx_utils import (
    MCP_DEFAULT_SSE_READ_TIMEOUT as MCP_DEFAULT_SSE_READ_TIMEOUT,
)
from mcp_client.shared._httpx_utils import (
    MCP_DEFAULT_TIMEOUT as MCP_DEFAULT_TIMEOUT,
)
from mcp_client.shared._httpx_utils import (
    McpHttpClientFactory as McpHttpClientFactory,
)
from mcp_client.shared._httpx_utils import (
    RedirectAwareAuth as RedirectAwareAuth,
)
from mcp_client.shared._httpx_utils import (
    _within_origin as _within_origin,
)
from mcp_client.shared._httpx_utils import (
    create_mcp_http_client as create_mcp_http_client,
)
from mcp_client.shared._httpx_utils import (
    next_request_within_origin as next_request_within_origin,
)
from mcp_client.shared._httpx_utils import (
    redirect_location as redirect_location,
)
from mcp_client.shared._httpx_utils import (
    redirect_note as redirect_note,
)
from mcp_client.shared._httpx_utils import (
    request_within_origin as request_within_origin,
)
from mcp_client.shared._httpx_utils import (
    sse_within_origin as sse_within_origin,
)
from mcp_client.shared._httpx_utils import (
    stream_within_origin as stream_within_origin,
)

sys.modules[__name__] = _implementation
