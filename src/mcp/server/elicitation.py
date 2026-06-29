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

    The spec's `PrimitiveSchemaDefinition` admits no `anyOf` or null type; optionality is
    expressed by omission from `required`, which pydantic already does for defaulted fields.
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

    Catches non-spec-valid renderings: bare `list[str]` (no enum), multi-primitive unions, nested models.
    """
    for field_name, prop in json_schema.get("properties", {}).items():
        try:
            PrimitiveSchemaDefinition.model_validate(prop)
        except ValidationError:
            raise TypeError(
                f"Elicitation schema field {field_name!r} rendered as {prop!r}, "
                f"which is not a valid PrimitiveSchemaDefinition"
            ) from None


def render_elicitation_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Render a model as the spec-valid `requested_schema` for an elicitation.

    Raises:
        TypeError: If a field renders as something the spec's `PrimitiveSchemaDefinition` does not accept.
    """
    json_schema = schema.model_json_schema(schema_generator=_ElicitationJsonSchema)
    _validate_rendered_properties(json_schema)
    return json_schema


async def elicit_with_validation(
    session: ServerSession,
    message: str,
    schema: type[ElicitSchemaModelT],
    related_request_id: RequestId | None = None,
) -> ElicitationResult[ElicitSchemaModelT]:
    """Elicit information from the client/user with schema validation (form mode).

    The client may show `message` to the user or, if an agent, generate the response itself.
    For sensitive data like credentials or OAuth flows, use `elicit_url` instead.

    Raises:
        ValueError: If the client accepted with no content, or content not matching the requested schema.
    """
    json_schema = render_elicitation_schema(schema)

    result = await session.elicit_form(
        message=message,
        requested_schema=json_schema,
        related_request_id=related_request_id,
    )

    if result.action == "accept":
        if result.content is None:
            raise ValueError("Received an accepted elicitation with no content")
        try:
            validated_data = schema.model_validate(result.content)
        except ValidationError as e:
            raise ValueError(
                "Received an accepted elicitation whose content does not match the requested schema"
            ) from e
        return AcceptedElicitation(data=validated_data)
    if result.action == "decline":
        return DeclinedElicitation()
    return CancelledElicitation()


async def elicit_url(
    session: ServerSession,
    message: str,
    url: str,
    elicitation_id: str,
    related_request_id: RequestId | None = None,
) -> UrlElicitationResult:
    """Elicit information from the user via out-of-band URL navigation (URL mode).

    Directs the user to an external URL where sensitive interactions (credentials, OAuth,
    payments) happen without passing data through the MCP client or LLM context. The result
    only indicates whether the user consented to navigate; when the out-of-band interaction
    completes, the server should send an ElicitCompleteNotification.
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
        raise ValueError(f"Unexpected elicitation action: {result.action}")
