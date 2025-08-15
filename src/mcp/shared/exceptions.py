from mcp.types import ErrorData


class McpError(Exception):
    """Exception raised when an MCP protocol error is received from a peer.

    This exception is raised when the remote MCP peer returns an error response
    instead of a successful result. It wraps the ErrorData received from the peer
    and provides access to the error code, message, and any additional data.

    Attributes:
        error: The ErrorData object received from the MCP peer containing
               error code, message, and optional additional data
    """

    error: ErrorData

    def __init__(self, error: ErrorData):
        """Initialize McpError with error data from the MCP peer.

        Args:
            error: ErrorData object containing the error details from the peer
        """
        super().__init__(error.message)
        self.error = error
