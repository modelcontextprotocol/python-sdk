import sys

import mcp_client.client.auth.oauth2 as _implementation
from mcp_client.client.auth.oauth2 import (
    _KNOWN_TOKEN_ENDPOINT_AUTH_METHODS as _KNOWN_TOKEN_ENDPOINT_AUTH_METHODS,
)
from mcp_client.client.auth.oauth2 import (
    _ORIGIN_URL as _ORIGIN_URL,
)
from mcp_client.client.auth.oauth2 import (
    _REGISTRATION_USABLE_TOKEN_ENDPOINT_AUTH_METHODS as _REGISTRATION_USABLE_TOKEN_ENDPOINT_AUTH_METHODS,
)
from mcp_client.client.auth.oauth2 import (
    _SECRET_TOKEN_ENDPOINT_AUTH_METHODS as _SECRET_TOKEN_ENDPOINT_AUTH_METHODS,
)
from mcp_client.client.auth.oauth2 import (
    OAuthClientProvider as OAuthClientProvider,
)
from mcp_client.client.auth.oauth2 import (
    OAuthContext as OAuthContext,
)
from mcp_client.client.auth.oauth2 import (
    PKCEParameters as PKCEParameters,
)
from mcp_client.client.auth.oauth2 import (
    TokenStorage as TokenStorage,
)
from mcp_client.client.auth.oauth2 import (
    _origin_issuer as _origin_issuer,
)
from mcp_client.client.auth.oauth2 import (
    check_registration_usable as check_registration_usable,
)
from mcp_client.client.auth.oauth2 import (
    logger as logger,
)

sys.modules[__name__] = _implementation
