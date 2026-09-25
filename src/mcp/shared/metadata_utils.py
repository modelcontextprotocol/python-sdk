import sys

import mcp_client.shared.metadata_utils as _implementation
from mcp_client.shared.metadata_utils import (
    get_display_name as get_display_name,
)

sys.modules[__name__] = _implementation
