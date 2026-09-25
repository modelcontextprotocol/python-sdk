import sys

import mcp_client.client.auth.exceptions as _implementation
from mcp_client.client.auth.exceptions import (
    OAuthFlowError as OAuthFlowError,
)
from mcp_client.client.auth.exceptions import (
    OAuthRegistrationError as OAuthRegistrationError,
)
from mcp_client.client.auth.exceptions import (
    OAuthTokenError as OAuthTokenError,
)

sys.modules[__name__] = _implementation
