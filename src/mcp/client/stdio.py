import sys

import mcp_client.client.stdio as _implementation
from mcp_client.client.stdio import (
    _EXIT_POLL_INTERVAL as _EXIT_POLL_INTERVAL,
)
from mcp_client.client.stdio import (
    _KILL_REAP_TIMEOUT as _KILL_REAP_TIMEOUT,
)
from mcp_client.client.stdio import (
    _WRITER_FLUSH_TIMEOUT as _WRITER_FLUSH_TIMEOUT,
)
from mcp_client.client.stdio import (
    DEFAULT_INHERITED_ENV_VARS as DEFAULT_INHERITED_ENV_VARS,
)
from mcp_client.client.stdio import (
    FORCE_KILL_TIMEOUT as FORCE_KILL_TIMEOUT,
)
from mcp_client.client.stdio import (
    PROCESS_TERMINATION_TIMEOUT as PROCESS_TERMINATION_TIMEOUT,
)
from mcp_client.client.stdio import (
    StdioServerParameters as StdioServerParameters,
)
from mcp_client.client.stdio import (
    _aclose_all as _aclose_all,
)
from mcp_client.client.stdio import (
    _close_pipe as _close_pipe,
)
from mcp_client.client.stdio import (
    _close_subprocess_transport as _close_subprocess_transport,
)
from mcp_client.client.stdio import (
    _create_platform_compatible_process as _create_platform_compatible_process,
)
from mcp_client.client.stdio import (
    _drain_stdout as _drain_stdout,
)
from mcp_client.client.stdio import (
    _get_executable_command as _get_executable_command,
)
from mcp_client.client.stdio import (
    _parse_line as _parse_line,
)
from mcp_client.client.stdio import (
    _stop_server_process as _stop_server_process,
)
from mcp_client.client.stdio import (
    _terminate_process_tree as _terminate_process_tree,
)
from mcp_client.client.stdio import (
    _wait_for_process_exit as _wait_for_process_exit,
)
from mcp_client.client.stdio import (
    get_default_environment as get_default_environment,
)
from mcp_client.client.stdio import (
    logger as logger,
)
from mcp_client.client.stdio import (
    stdio_client as stdio_client,
)

sys.modules[__name__] = _implementation
