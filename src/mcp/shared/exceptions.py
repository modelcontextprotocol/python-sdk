import sys

import mcp_client.shared.exceptions as _implementation
from mcp_client.shared.exceptions import (
    MCPDeprecationWarning as MCPDeprecationWarning,
)
from mcp_client.shared.exceptions import (
    MCPError as MCPError,
)
from mcp_client.shared.exceptions import (
    NoBackChannelError as NoBackChannelError,
)
from mcp_client.shared.exceptions import (
    UrlElicitationRequiredError as UrlElicitationRequiredError,
)

sys.modules[__name__] = _implementation
