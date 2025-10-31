"""Elicitation utilities for MCP servers."""

from __future__ import annotations

import types
from collections.abc import Sequence
from typing import Generic, Literal, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel

from mcp.server.session import ServerSession
from mcp.types import RequestId

ElicitSchemaModelT = TypeVar("ElicitSchemaModelT", bound=BaseModel)


class AcceptedElicitation(BaseModel, Generic[ElicitSchemaModelT]):
    """Result when user accepts the elicitation."""

    action: Literal["accept"] = "accept"
    data: ElicitSchemaModelT


class DeclinedElicitation(BaseModel):
    """Result when user declines the elicitation."""

    action: Literal["decline"] = "decline"


class CancelledElicitation(BaseModel):
    """Result when user cancels the elicitation."""

    action: Literal["cancel"] = "cancel"


ElicitationResult = AcceptedElicitation[ElicitSchemaModelT] | DeclinedElicitation | CancelledElicitation


# Primitive types allowed in elicitation schemas
_ELICITATION_PRIMITIVE_TYPES = (str, int, float, bool)


def _validate_elicitation_schema(schema: type[BaseModel]) -> None:
    """Validate that a Pydantic model only contains primitive field types."""
    for field_name, field_info in schema.model_fields.items():
        annotation = field_info.annotation

        if annotation is None or annotation is types.NoneType:
            continue
        elif _is_primitive_field(annotation):
            continue
        elif _is_string_sequence(annotation):
            continue
        else:
            raise TypeError(
                f"Elicitation schema field '{field_name}' must be a primitive type "
                f"{_ELICITATION_PRIMITIVE_TYPES}, a sequence of strings (list[str], etc.), "
                f"or Optional of these types. Nested models and complex types are not allowed."
            )


def _is_string_sequence(annotation: type) -> bool:
    """Check if annotation is a sequence of strings (list[str], Sequence[str], etc)."""
    origin = get_origin(annotation)
    # Check if it's a sequence-like type with str elements
    if origin and issubclass(origin, Sequence):
        args = get_args(annotation)
        # Should have single str type arg
        return len(args) == 1 and args[0] is str
    return False


def _is_primitive_field(annotation: type) -> bool:
    """Check if a field is a primitive type allowed in elicitation schemas."""
    # Handle basic primitive types
    if annotation in _ELICITATION_PRIMITIVE_TYPES:
        return True

    # Handle Union types
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = get_args(annotation)
        # All args must be primitive types or None
        return all(arg is types.NoneType or arg in _ELICITATION_PRIMITIVE_TYPES for arg in args)

    return False


async def elicit_with_validation(
    session: ServerSession,
    message: str,
    schema: type[ElicitSchemaModelT],
    related_request_id: RequestId | None = None,
) -> ElicitationResult[ElicitSchemaModelT]:
    """Elicit information from the client/user with schema validation.

    This method can be used to interactively ask for additional information from the
    client within a tool's execution. The client might display the message to the
    user and collect a response according to the provided schema. Or in case a
    client is an agent, it might decide how to handle the elicitation -- either by asking
    the user or automatically generating a response.
    """
    # Validate that schema only contains primitive types and fail loudly if not
    _validate_elicitation_schema(schema)

    json_schema = schema.model_json_schema()

    result = await session.elicit(
        message=message,
        requestedSchema=json_schema,
        related_request_id=related_request_id,
    )

    if result.action == "accept" and result.content is not None:
        # Validate and parse the content using the schema
        validated_data = schema.model_validate(result.content)
        return AcceptedElicitation(data=validated_data)
    elif result.action == "decline":
        return DeclinedElicitation()
    elif result.action == "cancel":
        return CancelledElicitation()
    else:
        # This should never happen, but handle it just in case
        raise ValueError(f"Unexpected elicitation action: {result.action}")
