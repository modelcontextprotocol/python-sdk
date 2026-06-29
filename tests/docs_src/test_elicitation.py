"""`docs/tutorial/elicitation.md`: every claim the page makes, proved against the real SDK."""

from typing import Literal

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    ElicitCompleteNotification,
    ElicitRequestFormParams,
    ElicitRequestParams,
    ElicitRequestURLParams,
    ElicitResult,
    TextContent,
)
from pydantic import BaseModel

from docs_src.elicitation import tutorial001, tutorial002, tutorial003, tutorial004
from mcp import Client, MCPError
from mcp.client import ClientRequestContext
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_an_accepted_answer_resumes_the_tool() -> None:
    async def on_elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="accept", content={"accept_alternative": True, "date": "2025-12-26"})

    async with Client(tutorial001.mcp, mode="legacy", elicitation_callback=on_elicit) as client:
        result = await client.call_tool("book_table", {"date": "2025-12-25", "party_size": 2})
        assert not result.is_error
        assert result.content == [TextContent(type="text", text="Booked a table for 2 on 2025-12-26.")]


async def test_an_alternative_that_is_also_full_is_asked_about_again() -> None:
    """tutorial001: the accepted date goes back through `book_table`, so a full date is re-asked, not booked."""
    asked: list[str] = []

    async def on_elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        asked.append(params.message)
        date = "2025-12-25" if len(asked) == 1 else "2025-12-27"
        return ElicitResult(action="accept", content={"accept_alternative": True, "date": date})

    async with Client(tutorial001.mcp, mode="legacy", elicitation_callback=on_elicit) as client:
        result = await client.call_tool("book_table", {"date": "2025-12-25", "party_size": 2})
    assert result.content == [TextContent(type="text", text="Booked a table for 2 on 2025-12-27.")]
    assert asked == [
        "No tables for 2 on 2025-12-25. Would you like to try another date?",
        "No tables for 2 on 2025-12-25. Would you like to try another date?",
    ]


async def test_the_client_receives_the_message_and_the_generated_schema() -> None:
    received: list[ElicitRequestParams] = []

    async def on_elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="accept", content={"accept_alternative": False})

    async with Client(tutorial001.mcp, mode="legacy", elicitation_callback=on_elicit) as client:
        await client.call_tool("book_table", {"date": "2025-12-25", "party_size": 2})
    (params,) = received
    assert isinstance(params, ElicitRequestFormParams)
    assert params.message == "No tables for 2 on 2025-12-25. Would you like to try another date?"
    assert params.requested_schema == snapshot(
        {
            "properties": {
                "accept_alternative": {
                    "description": "Try another date?",
                    "title": "Accept Alternative",
                    "type": "boolean",
                },
                "date": {
                    "default": "2025-12-26",
                    "description": "Alternative date (YYYY-MM-DD)",
                    "title": "Date",
                    "type": "string",
                },
            },
            "required": ["accept_alternative"],
            "title": "AlternativeDate",
            "type": "object",
        }
    )


async def test_decline_and_cancel_are_ordinary_return_values() -> None:
    async def on_decline(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="decline")

    async def on_cancel(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="cancel")

    async with Client(tutorial001.mcp, mode="legacy", elicitation_callback=on_decline) as client:
        declined = await client.call_tool("book_table", {"date": "2025-12-25", "party_size": 2})
    async with Client(tutorial001.mcp, mode="legacy", elicitation_callback=on_cancel) as client:
        cancelled = await client.call_tool("book_table", {"date": "2025-12-25", "party_size": 2})
    assert declined.content == [TextContent(type="text", text="No booking made.")]
    assert not declined.is_error
    assert cancelled.content == [TextContent(type="text", text="No booking made.")]


async def test_a_tool_that_does_not_ask_needs_nothing_from_the_client() -> None:
    async with Client(tutorial001.mcp, mode="legacy") as client:
        result = await client.call_tool("book_table", {"date": "2025-12-30", "party_size": 4})
        assert result.content == [TextContent(type="text", text="Booked a table for 4 on 2025-12-30.")]


async def test_an_answer_that_does_not_match_the_schema_never_reaches_the_tool_code() -> None:
    """`!!! tip`: the client's content is validated against the model; a mismatch fails the call."""

    async def on_elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="accept", content={"accept_alternative": "maybe"})

    async with Client(tutorial001.mcp, mode="legacy", elicitation_callback=on_elicit) as client:
        result = await client.call_tool("book_table", {"date": "2025-12-25", "party_size": 2})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "does not match the requested schema" in result.content[0].text


class Address(BaseModel):
    city: str


class Applicant(BaseModel):
    name: str
    address: Address


class Seating(BaseModel):
    area: Literal["inside", "terrace"]


schema_gate_server = MCPServer("Bistro")
"""The `!!! warning` claims: what the elicitation schema gate accepts and rejects."""


@schema_gate_server.tool()
async def sign_up(ctx: Context) -> str:
    """Collect the new customer's details."""
    return str(await ctx.elicit(message="Who are you?", schema=Applicant))


@schema_gate_server.tool()
async def choose_seating(ctx: Context) -> str:
    """Ask where the party wants to sit."""
    result = await ctx.elicit(message="Where would you like to sit?", schema=Seating)
    assert result.action == "accept"
    return result.data.area


async def test_a_nested_model_is_rejected_before_anything_is_sent() -> None:
    """`!!! warning`: a non-primitive field raises `TypeError` inside `ctx.elicit`, with this exact message."""
    async with Client(schema_gate_server, mode="legacy") as client:
        result = await client.call_tool("sign_up", {})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == (
        "Error executing tool sign_up: Elicitation schema field 'address' rendered as "
        "{'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition"
    )


async def test_a_literal_field_passes_the_gate_as_an_enum() -> None:
    """`!!! warning`: a `Literal[...]` of strings renders as a JSON Schema `enum`, which the spec allows."""
    received: list[ElicitRequestParams] = []

    async def on_elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="accept", content={"area": "terrace"})

    async with Client(schema_gate_server, mode="legacy", elicitation_callback=on_elicit) as client:
        result = await client.call_tool("choose_seating", {})
    assert result.content == [TextContent(type="text", text="terrace")]
    (params,) = received
    assert isinstance(params, ElicitRequestFormParams)
    assert params.requested_schema["properties"]["area"] == snapshot(
        {"enum": ["inside", "terrace"], "title": "Area", "type": "string"}
    )


async def test_url_mode_sends_a_url_and_gets_consent_back_not_data() -> None:
    received: list[ElicitRequestParams] = []

    async def on_elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="accept")

    async with Client(tutorial002.mcp, mode="legacy", elicitation_callback=on_elicit) as client:
        result = await client.call_tool("pay_deposit", {"booking_id": "b42"})
    assert result.content == [TextContent(type="text", text="Complete the payment in your browser.")]
    (params,) = received
    assert isinstance(params, ElicitRequestURLParams)
    assert params.url == "https://pay.example.com/deposit/b42"
    assert params.elicitation_id == "deposit-b42"


async def test_a_declined_url_elicitation_is_an_ordinary_return_value() -> None:
    async def on_elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="decline")

    async with Client(tutorial002.mcp, mode="legacy", elicitation_callback=on_elicit) as client:
        result = await client.call_tool("pay_deposit", {"booking_id": "b42"})
    assert result.content == [TextContent(type="text", text="No deposit taken. The booking expires in one hour.")]


async def test_send_elicit_complete_notifies_the_client_with_the_same_id() -> None:
    notifications: list[object] = []

    async def on_message(message: object) -> None:
        notifications.append(message)

    async with Client(tutorial002.mcp, mode="legacy", message_handler=on_message) as client:
        result = await client.call_tool("confirm_deposit", {"booking_id": "b42"})
    assert result.content == [TextContent(type="text", text="Deposit received for booking b42.")]
    (notification,) = notifications
    assert isinstance(notification, ElicitCompleteNotification)
    assert notification.params.elicitation_id == "deposit-b42"


async def test_the_docs_client_callback_handles_both_modes() -> None:
    async with Client(tutorial001.mcp, mode="legacy", elicitation_callback=tutorial003.handle_elicitation) as client:
        booked = await client.call_tool("book_table", {"date": "2025-12-25", "party_size": 2})
    async with Client(tutorial002.mcp, mode="legacy", elicitation_callback=tutorial003.handle_elicitation) as client:
        paid = await client.call_tool("pay_deposit", {"booking_id": "b42"})
    assert booked.content == [TextContent(type="text", text="Booked a table for 2 on 2025-12-27.")]
    assert paid.content == [TextContent(type="text", text="Complete the payment in your browser.")]


async def test_a_client_without_the_callback_cannot_be_asked() -> None:
    """`!!! check`: no `elicitation_callback` means no `elicitation` capability; the call is a protocol error."""
    async with Client(tutorial001.mcp, mode="legacy") as client:
        with pytest.raises(MCPError, match="Elicitation not supported"):
            await client.call_tool("book_table", {"date": "2025-12-25", "party_size": 2})


async def test_resolver_asks_only_when_the_folder_is_not_empty() -> None:
    tutorial004._FOLDERS.update({"/tmp/empty": [], "/tmp/project": ["main.py", "README.md"]})
    asked: list[str] = []

    async def on_elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        asked.append(params.message)
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(tutorial004.mcp, mode="legacy", elicitation_callback=on_elicit) as client:
        empty = await client.call_tool("delete_folder", {"path": "/tmp/empty"})
        non_empty = await client.call_tool("delete_folder", {"path": "/tmp/project"})

    assert empty.content == [TextContent(type="text", text="deleted /tmp/empty")]
    assert non_empty.content == [TextContent(type="text", text="deleted /tmp/project")]
    assert asked == ["/tmp/project has 2 file(s). Delete anyway?"]


async def test_the_resolved_parameter_is_hidden_from_the_tool_schema() -> None:
    async with Client(tutorial004.mcp, mode="legacy") as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.name == "delete_folder"
        assert set(tool.input_schema["properties"]) == {"path"}


@pytest.mark.parametrize(
    ("action", "content", "expected"),
    [
        ("accept", {"ok": False}, "kept the folder"),
        ("decline", None, "declined: folder not deleted"),
        ("cancel", None, "cancelled: folder not deleted"),
    ],
)
async def test_the_tool_branches_on_every_elicitation_outcome(
    action: Literal["accept", "decline", "cancel"],
    content: dict[str, str | int | float | bool | list[str] | None] | None,
    expected: str,
) -> None:
    tutorial004._FOLDERS["/tmp/project"] = ["main.py", "README.md"]

    async def on_elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action=action, content=content)

    async with Client(tutorial004.mcp, mode="legacy", elicitation_callback=on_elicit) as client:
        result = await client.call_tool("delete_folder", {"path": "/tmp/project"})
    assert result.content == [TextContent(type="text", text=expected)]
