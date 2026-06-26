"""Elicitation utilities for MCP servers."""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from mcp_types import RequestId

# Internal surface package; imported as the gate's source of truth for spec-valid property schemas.
from mcp_types.v2025_11_25 import PrimitiveSchemaDefinition
from pydantic import BaseModel, ValidationError
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema
from typing_extensions import TypeAliasType

from mcp.server.session import ServerSession

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


ElicitationResult = TypeAliasType(
    "ElicitationResult",
    AcceptedElicitation[ElicitSchemaModelT] | DeclinedElicitation | CancelledElicitation,
    type_params=(ElicitSchemaModelT,),
)


class AcceptedUrlElicitation(BaseModel):
    """Result when user accepts a URL mode elicitation."""

    action: Literal["accept"] = "accept"


UrlElicitationResult = AcceptedUrlElicitation | DeclinedElicitation | CancelledElicitation


class _ElicitationJsonSchema(GenerateJsonSchema):
    """JSON-Schema generator that flattens `T | None` to `T` and drops `None` defaults.

    The spec's `PrimitiveSchemaDefinition` admits no `anyOf` or null type; an
    optional field is expressed by leaving it out of `required`, which pydantic
    already does for any field with a default.
    """

    def nullable_schema(self, schema: core_schema.NullableSchema) -> JsonSchemaValue:
        return self.generate_inner(schema["schema"])

    def default_schema(self, schema: core_schema.WithDefaultSchema) -> JsonSchemaValue:
        result = super().default_schema(schema)
        if result.get("default") is None:
            result.pop("default", None)
        return result


def _validate_rendered_properties(json_schema: dict[str, Any]) -> None:
    """Reject any `properties` entry the spec's `PrimitiveSchemaDefinition` won't accept.

    Catches whatever the renderer let through that isn't spec-valid: bare
    `list[str]` (no enum), multi-primitive unions, nested models.
    """
    for field_name, prop in json_schema.get("properties", {}).items():
        try:
            PrimitiveSchemaDefinition.model_validate(prop)
        except ValidationError:
            raise TypeError(
                f"Elicitation schema field {field_name!r} rendered as {prop!r}, "
                f"which is not a valid PrimitiveSchemaDefinition"
            ) from None


async def elicit_with_validation(
    session: ServerSession,
    message: str,
    schema: type[ElicitSchemaModelT],
    related_request_id: RequestId | None = None,
) -> ElicitationResult[ElicitSchemaModelT]:
    """Elicit information from the client/user with schema validation (form mode).

    This method can be used to interactively ask for additional information from the
    client within a tool's execution. The client might display the message to the
    user and collect a response according to the provided schema. If the client
    is an agent, it might decide how to handle the elicitation -- either by asking
    the user or automatically generating a response.

    For sensitive data like credentials or OAuth flows, use elicit_url() instead.
    """
    json_schema = schema.model_json_schema(schema_generator=_ElicitationJsonSchema)
    _validate_rendered_properties(json_schema)

    result = await session.elicit_form(
        message=message,
        requested_schema=json_schema,
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
    else:  # pragma: no cover
        # This should never happen, but handle it just in case
        raise ValueError(f"Unexpected elicitation action: {result.action}")


async def elicit_url(
    session: ServerSession,
    message: str,
    url: str,
    elicitation_id: str,
    related_request_id: RequestId | None = None,
) -> UrlElicitationResult:
    """Elicit information from the user via out-of-band URL navigation (URL mode).

    This method directs the user to an external URL where sensitive interactions can
    occur without passing data through the MCP client. Use this for:
    - Collecting sensitive credentials (API keys, passwords)
    - OAuth authorization flows with third-party services
    - Payment and subscription flows
    - Any interaction where data should not pass through the LLM context

    The response indicates whether the user consented to navigate to the URL.
    The actual interaction happens out-of-band. When the elicitation completes,
    the server should send an ElicitCompleteNotification to notify the client.

    Args:
        session: The server session
        message: Human-readable explanation of why the interaction is needed
        url: The URL the user should navigate to
        elicitation_id: Unique identifier for tracking this elicitation
        related_request_id: Optional ID of the request that triggered this elicitation

    Returns:
        UrlElicitationResult indicating accept, decline, or cancel
    """
    result = await session.elicit_url(
        message=message,
        url=url,
        elicitation_id=elicitation_id,
        related_request_id=related_request_id,
    )

    if result.action == "accept":
        return AcceptedUrlElicitation()
    elif result.action == "decline":
        return DeclinedElicitation()
    elif result.action == "cancel":
        return CancelledElicitation()
    else:  # pragma: no cover
        # This should never happen, but handle it just in case
        raise ValueError(f"Unexpected elicitation action: {result.action}")
