import sys

import mcp_client.shared._otel as _implementation
from mcp_client.shared._otel import (
    _tracer as _tracer,
)
from mcp_client.shared._otel import (
    extract_trace_context as extract_trace_context,
)
from mcp_client.shared._otel import (
    inject_trace_context as inject_trace_context,
)
from mcp_client.shared._otel import (
    otel_span as otel_span,
)

sys.modules[__name__] = _implementation
