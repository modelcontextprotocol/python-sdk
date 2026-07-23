"""Five ways to type a tool parameter so MCPServer derives and enforces inputSchema."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, create_model

# pydantic requires typing_extensions.TypedDict (not typing.TypedDict) on Python < 3.12
# when a TypedDict is used as a field/parameter type.
from typing_extensions import TypedDict

from mcp.server.mcpserver import MCPServer
from stories._hosting import run_server_from_args


class PersonModel(BaseModel):
    name: str
    title: str = "friend"


class PersonTD(TypedDict):
    name: str
    title: str


@dataclass
class PersonDC:
    name: str
    title: str = "friend"


# The four types above are declared in source. This fifth one is not: a caller
# holding an external JSON Schema (from OpenAPI, a config file, a DB row) builds
# the pydantic model at runtime with create_model, then hands it to @mcp.tool()
# exactly like a hand-written BaseModel. MCPServer reflects over it the same way.
PERSON_JSON_SCHEMA: dict[str, Any] = {
    "properties": {"name": {"type": "string"}, "title": {"type": "string", "default": "friend"}},
    "required": ["name"],
}
if TYPE_CHECKING:
    # A create_model() result is opaque to static tools: its fields don't exist
    # until runtime, and a runtime variable can't appear in a type annotation.
    # Alias it to a declared model of the same shape so type checkers can see
    # `name`/`title`; at runtime the dynamic class below is what @mcp.tool() sees.
    PersonDynamic = PersonModel
else:
    # `required` is optional in JSON Schema — a schema of all-optional properties
    # omits it — so default to an empty list rather than indexing it directly.
    _required = PERSON_JSON_SCHEMA.get("required", [])
    _dynamic_fields: dict[str, Any] = {
        field_name: (str, ... if field_name in _required else field_schema.get("default"))
        for field_name, field_schema in PERSON_JSON_SCHEMA["properties"].items()
    }
    PersonDynamic = create_model("PersonDynamic", **_dynamic_fields)


def build_server() -> MCPServer:
    mcp = MCPServer("schema-validators-example")

    @mcp.tool()
    def greet_pydantic(who: PersonModel) -> str:
        """`who` arrives as a validated PersonModel instance."""
        return f"Hello {who.name}, my {who.title}"

    @mcp.tool()
    def greet_typeddict(who: PersonTD) -> str:
        """`who` arrives as a plain dict; TypedDict drives the schema and editor hints."""
        return f"Hello {who['name']}, my {who['title']}"

    @mcp.tool()
    def greet_dataclass(who: PersonDC) -> str:
        """`who` arrives as a PersonDC instance (pydantic coerces the wire dict)."""
        return f"Hello {who.name}, my {who.title}"

    @mcp.tool()
    def greet_dict(who: dict[str, Any]) -> str:
        """`who` is a free-form object — any dict passes; the handler must check it."""
        return f"Hello {who['name']}, my {who.get('title', 'friend')}"

    @mcp.tool()
    def greet_dynamic(who: PersonDynamic) -> str:
        """`who`'s type was built at runtime by create_model, not declared in source.

        It validates and behaves like the ``PersonModel`` variant; the only
        difference is that its class is assembled from a JSON Schema dict at import
        time rather than written out as a ``class`` statement.
        """
        return f"Hello {who.name}, my {who.title}"

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
