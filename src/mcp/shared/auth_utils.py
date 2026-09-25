import sys

import mcp_client.shared.auth_utils as _implementation
from mcp_client.shared.auth_utils import (
    calculate_token_expiry as calculate_token_expiry,
)
from mcp_client.shared.auth_utils import (
    check_resource_allowed as check_resource_allowed,
)
from mcp_client.shared.auth_utils import (
    resource_url_from_server_url as resource_url_from_server_url,
)

sys.modules[__name__] = _implementation
