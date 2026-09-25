import sys

import mcp_client.os.posix.utilities as _implementation
from mcp_client.os.posix.utilities import (
    _GROUP_POLL_INTERVAL as _GROUP_POLL_INTERVAL,
)
from mcp_client.os.posix.utilities import (
    _group_alive as _group_alive,
)
from mcp_client.os.posix.utilities import (
    logger as logger,
)
from mcp_client.os.posix.utilities import (
    terminate_posix_process_tree as terminate_posix_process_tree,
)

sys.modules[__name__] = _implementation
