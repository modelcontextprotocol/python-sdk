import sys

import mcp_client.client.auth.extensions.identity_assertion as _implementation
from mcp_client.client.auth.extensions.identity_assertion import (
    _DEFAULT_PORTS as _DEFAULT_PORTS,
)
from mcp_client.client.auth.extensions.identity_assertion import (
    IdentityAssertionOAuthProvider as IdentityAssertionOAuthProvider,
)
from mcp_client.client.auth.extensions.identity_assertion import (
    _origin as _origin,
)

sys.modules[__name__] = _implementation
