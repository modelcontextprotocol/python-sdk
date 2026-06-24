"""Four ways to type a tool parameter so MCPServer derives and enforces inputSchema."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

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

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
