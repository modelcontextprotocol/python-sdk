from enum import Enum

DEFAULT_QUALIFIER = "default"  # Shared qualifier for all ResultType enums

class ToolResultType(str, Enum):
    """Result type for tool executions: DEFAULT, SUCCESS, or ERROR."""
    DEFAULT = DEFAULT_QUALIFIER
    SUCCESS = "success"
    ERROR = "error"

class PromptResultType(str, Enum):
    """Result type for prompt executions: DEFAULT, SUCCESS, or ERROR."""
    DEFAULT = DEFAULT_QUALIFIER
    SUCCESS = "success"
    ERROR = "error"

class ResourceResultType(str, Enum):
    """Result type for resource executions: DEFAULT, SUCCESS, or ERROR."""
    DEFAULT = DEFAULT_QUALIFIER
    SUCCESS = "success"
    ERROR = "error"