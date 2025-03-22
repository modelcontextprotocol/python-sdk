from typing import Literal

from pydantic import BaseModel, ValidationError

ErrorCode = Literal["invalid_request", "invalid_client"]


class ErrorResponse(BaseModel):
    error: ErrorCode
    error_description: str


class OAuthError(Exception):
    """
    Base class for all OAuth errors.
    """

    error_code: ErrorCode

    def __init__(self, error_description: str):
        super().__init__(error_description)
        self.error_description = error_description

    def error_response(self) -> ErrorResponse:
        return ErrorResponse(
            error=self.error_code,
            error_description=self.error_description,
        )


def stringify_pydantic_error(validation_error: ValidationError) -> str:
    return "\n".join(
        f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
        for e in validation_error.errors()
    )
