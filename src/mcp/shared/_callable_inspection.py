import sys

import mcp_client.shared._callable_inspection as _implementation
from mcp_client.shared._callable_inspection import (
    AwaitableCallable as AwaitableCallable,
)
from mcp_client.shared._callable_inspection import (
    T as T,
)
from mcp_client.shared._callable_inspection import (
    is_async_callable as is_async_callable,
)

sys.modules[__name__] = _implementation
