import sys

import mcp_client.shared.extension as _implementation
from mcp_client.shared.extension import (
    _IDENTIFIER_RE as _IDENTIFIER_RE,
)
from mcp_client.shared.extension import (
    _LABEL as _LABEL,
)
from mcp_client.shared.extension import (
    _NAME as _NAME,
)
from mcp_client.shared.extension import (
    validate_extension_identifier as validate_extension_identifier,
)

sys.modules[__name__] = _implementation
