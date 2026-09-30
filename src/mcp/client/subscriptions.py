import sys

import mcp_client.client.subscriptions as _implementation
from mcp_client.client.subscriptions import (
    _MAX_PENDING_EVENTS as _MAX_PENDING_EVENTS,
)
from mcp_client.client.subscriptions import (
    ListenNotSupportedError as ListenNotSupportedError,
)
from mcp_client.client.subscriptions import (
    ListenRoute as ListenRoute,
)
from mcp_client.client.subscriptions import (
    OnEvent as OnEvent,
)
from mcp_client.client.subscriptions import (
    PromptsListChanged as PromptsListChanged,
)
from mcp_client.client.subscriptions import (
    ResourcesListChanged as ResourcesListChanged,
)
from mcp_client.client.subscriptions import (
    ResourceUpdated as ResourceUpdated,
)
from mcp_client.client.subscriptions import (
    ServerEvent as ServerEvent,
)
from mcp_client.client.subscriptions import (
    Subscription as Subscription,
)
from mcp_client.client.subscriptions import (
    SubscriptionLost as SubscriptionLost,
)
from mcp_client.client.subscriptions import (
    ToolsListChanged as ToolsListChanged,
)
from mcp_client.client.subscriptions import (
    _listen_ids as _listen_ids,
)
from mcp_client.client.subscriptions import (
    _SubscriptionEnd as _SubscriptionEnd,
)
from mcp_client.client.subscriptions import (
    listen as listen,
)

sys.modules[__name__] = _implementation
