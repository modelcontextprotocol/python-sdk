"""Custom exceptions for FastMCP."""


class FastMCPError(Exception):
    """Base exception class for all FastMCP-related errors.

    This is the root exception type for all errors that can occur within
    the FastMCP framework. Specific error types inherit from this class.
    """


class ValidationError(FastMCPError):
    """Raised when parameter or return value validation fails.

    This exception is raised when input arguments don't match a tool's
    input schema, or when output values fail validation against output schemas.
    It typically indicates incorrect data types, missing required fields,
    or values that don't meet schema constraints.
    """


class ResourceError(FastMCPError):
    """Raised when resource operations fail.

    This exception is raised for resource-related errors such as:

    - Resource not found for a given URI
    - Resource content cannot be read or generated
    - Resource template parameter validation failures
    - Resource access permission errors
    """


class ToolError(FastMCPError):
    """Raised when tool operations fail.

    This exception is raised for tool-related errors such as:

    - Tool not found for a given name
    - Tool execution failures or unhandled exceptions
    - Tool registration conflicts or validation errors
    - Tool parameter or result processing errors
    """


class InvalidSignature(Exception):
    """Raised when a function signature is incompatible with FastMCP.

    This exception is raised when trying to register a function as a tool,
    resource, or prompt that has an incompatible signature. This can occur
    when functions have unsupported parameter types, complex annotations
    that cannot be converted to JSON schema, or other signature issues.
    """
