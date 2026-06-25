from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from mcp.server import Server, ServerRequestContext


@dataclass
class Catalog:
    books: list[str]

    def search(self, query: str) -> list[str]:
        return [title for title in self.books if query.lower() in title.lower()]


@asynccontextmanager
async def lifespan(server: Server[Catalog]) -> AsyncIterator[Catalog]:
    yield Catalog(books=["Dune", "Dune Messiah", "Children of Dune"])


SEARCH_BOOKS = Tool(
    name="search_books",
    description="Search the catalog by title or author.",
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)


async def list_tools(ctx: ServerRequestContext[Catalog], params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[SEARCH_BOOKS])


async def call_tool(ctx: ServerRequestContext[Catalog], params: CallToolRequestParams) -> CallToolResult:
    matches = ctx.lifespan_context.search((params.arguments or {})["query"])
    text = f"Found {len(matches)} books: {', '.join(matches)}."
    return CallToolResult(content=[TextContent(type="text", text=text)])


server = Server("Bookshop", lifespan=lifespan, on_list_tools=list_tools, on_call_tool=call_tool)
