import sys

import mcp_client.client.extension as _implementation
from mcp_client.client.extension import (
    _CLAIM_METHODS as _CLAIM_METHODS,
)
from mcp_client.client.extension import (
    _RESERVED_WIRE_ALIASES as _RESERVED_WIRE_ALIASES,
)
from mcp_client.client.extension import (
    ClaimContext as ClaimContext,
)
from mcp_client.client.extension import (
    ClaimedT as ClaimedT,
)
from mcp_client.client.extension import (
    ClientExtension as ClientExtension,
)
from mcp_client.client.extension import (
    NotificationBinding as NotificationBinding,
)
from mcp_client.client.extension import (
    NotifyParamsT as NotifyParamsT,
)
from mcp_client.client.extension import (
    ResultClaim as ResultClaim,
)
from mcp_client.client.extension import (
    UnexpectedClaimedResult as UnexpectedClaimedResult,
)
from mcp_client.client.extension import (
    _AdvertiseOnly as _AdvertiseOnly,
)
from mcp_client.client.extension import (
    _wire_keys as _wire_keys,
)
from mcp_client.client.extension import (
    advertise as advertise,
)

sys.modules[__name__] = _implementation
