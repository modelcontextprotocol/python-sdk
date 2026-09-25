import sys

import mcp_client.shared.tool_name_validation as _implementation
from mcp_client.shared.tool_name_validation import (
    SEP_986_URL as SEP_986_URL,
)
from mcp_client.shared.tool_name_validation import (
    TOOL_NAME_REGEX as TOOL_NAME_REGEX,
)
from mcp_client.shared.tool_name_validation import (
    ToolNameValidationResult as ToolNameValidationResult,
)
from mcp_client.shared.tool_name_validation import (
    issue_tool_name_warning as issue_tool_name_warning,
)
from mcp_client.shared.tool_name_validation import (
    logger as logger,
)
from mcp_client.shared.tool_name_validation import (
    validate_and_warn_tool_name as validate_and_warn_tool_name,
)
from mcp_client.shared.tool_name_validation import (
    validate_tool_name as validate_tool_name,
)

sys.modules[__name__] = _implementation
