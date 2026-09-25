import sys

import mcp_client.client.auth.extensions.client_credentials as _implementation
from mcp_client.client.auth.extensions.client_credentials import (
    ClientCredentialsOAuthProvider as ClientCredentialsOAuthProvider,
)
from mcp_client.client.auth.extensions.client_credentials import (
    PrivateKeyJWTOAuthProvider as PrivateKeyJWTOAuthProvider,
)
from mcp_client.client.auth.extensions.client_credentials import (
    SignedJWTParameters as SignedJWTParameters,
)
from mcp_client.client.auth.extensions.client_credentials import (
    _checked_issuer as _checked_issuer,
)
from mcp_client.client.auth.extensions.client_credentials import (
    _preferred_authorization_server as _preferred_authorization_server,
)
from mcp_client.client.auth.extensions.client_credentials import (
    _require_metadata_for_configured_issuer as _require_metadata_for_configured_issuer,
)
from mcp_client.client.auth.extensions.client_credentials import (
    static_assertion_provider as static_assertion_provider,
)

sys.modules[__name__] = _implementation
