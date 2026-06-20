from __future__ import annotations

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, Field

from mcp.server.mcpserver.utilities._schema_generator import ExternalSchemaRefError, StrictJsonSchema


def test_same_document_refs_pass():
    class Inner(BaseModel):
        x: int

    class Model(BaseModel):
        inner: Inner

    schema = Model.model_json_schema(schema_generator=StrictJsonSchema)
    assert "$defs" in schema
    assert schema["properties"]["inner"]["$ref"] == "#/$defs/Inner"


def test_external_ref_in_property_rejected():
    class Model(BaseModel):
        profile: Annotated[dict[str, Any], Field(json_schema_extra={"$ref": "https://evil.example/s.json"})]

    with pytest.raises(ExternalSchemaRefError, match="https://evil.example/s.json"):
        Model.model_json_schema(schema_generator=StrictJsonSchema)


def test_external_ref_nested_in_list_rejected():
    class Model(BaseModel):
        items: Annotated[
            list[str],
            Field(json_schema_extra={"prefixItems": [{"$ref": "https://evil.example/a.json"}]}),
        ]

    with pytest.raises(ExternalSchemaRefError, match="https://evil.example/a.json"):
        Model.model_json_schema(schema_generator=StrictJsonSchema)
