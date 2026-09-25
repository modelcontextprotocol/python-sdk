import sys

import mcp_client.shared.auth as _implementation
from mcp_client.shared.auth import (
    DEFAULT_GRANT_TYPES as DEFAULT_GRANT_TYPES,
)
from mcp_client.shared.auth import (
    JWT_BEARER_GRANT_TYPE as JWT_BEARER_GRANT_TYPE,
)
from mcp_client.shared.auth import (
    AuthorizationCodeResult as AuthorizationCodeResult,
)
from mcp_client.shared.auth import (
    InvalidRedirectUriError as InvalidRedirectUriError,
)
from mcp_client.shared.auth import (
    InvalidScopeError as InvalidScopeError,
)
from mcp_client.shared.auth import (
    OAuthClientInformationFull as OAuthClientInformationFull,
)
from mcp_client.shared.auth import (
    OAuthClientMetadata as OAuthClientMetadata,
)
from mcp_client.shared.auth import (
    OAuthClientMetadataBase as OAuthClientMetadataBase,
)
from mcp_client.shared.auth import (
    OAuthMetadata as OAuthMetadata,
)
from mcp_client.shared.auth import (
    OAuthToken as OAuthToken,
)
from mcp_client.shared.auth import (
    ProtectedResourceMetadata as ProtectedResourceMetadata,
)
from mcp_client.shared.auth import (
    TokenEndpointAuthMethod as TokenEndpointAuthMethod,
)
from mcp_client.shared.auth import (
    _empty_str_to_none as _empty_str_to_none,
)

sys.modules[__name__] = _implementation
