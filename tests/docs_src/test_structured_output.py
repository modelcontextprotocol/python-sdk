"""`docs/servers/structured-output.md`: every claim the page makes, proved against the real SDK."""

import logging

import pytest
from inline_snapshot import snapshot
from mcp_types import EmbeddedResource, ImageContent, TextContent, TextResourceContents

from docs_src.structured_output import (
    tutorial001,
    tutorial002,
    tutorial003,
    tutorial004,
    tutorial005,
    tutorial006,
    tutorial007,
    tutorial008,
    tutorial009,
)
from mcp import Client
from mcp.server import MCPServer
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import InvalidSignature

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_scalar_return_is_wrapped() -> None:
    """tutorial001: `-> int` becomes a `{"result": ...}` output schema and fills both channels."""
    async with Client(tutorial001.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema == snapshot(
            {
                "properties": {"result": {"title": "Result", "type": "integer"}},
                "required": ["result"],
                "title": "get_temperatureOutput",
                "type": "object",
            }
        )
        result = await client.call_tool("get_temperature", {"city": "London"})
        assert not result.is_error
        assert result.content == [TextContent(type="text", text="17")]
        assert result.structured_content == {"result": 17}


async def test_basemodel_is_the_schema() -> None:
    """tutorial002: a `BaseModel` return type is the output schema itself: no wrapper."""
    async with Client(tutorial002.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema == snapshot(
            {
                "properties": {
                    "temperature": {"description": "Degrees Celsius.", "title": "Temperature", "type": "number"},
                    "humidity": {"description": "Relative humidity, 0 to 1.", "title": "Humidity", "type": "number"},
                    "conditions": {"title": "Conditions", "type": "string"},
                },
                "required": ["temperature", "humidity", "conditions"],
                "title": "WeatherData",
                "type": "object",
            }
        )
        result = await client.call_tool("get_weather", {"city": "London"})
        assert result.structured_content == {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
        serialized = '{\n  "temperature": 16.2,\n  "humidity": 0.83,\n  "conditions": "Overcast"\n}'
        assert result.content == [TextContent(type="text", text=serialized)]


async def test_typeddict_produces_the_same_schema() -> None:
    """tutorial003: a `TypedDict` return type produces the same object schema as the `BaseModel`."""
    async with Client(tutorial003.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema == snapshot(
            {
                "properties": {
                    "temperature": {"title": "Temperature", "type": "number"},
                    "humidity": {"title": "Humidity", "type": "number"},
                    "conditions": {"title": "Conditions", "type": "string"},
                },
                "required": ["temperature", "humidity", "conditions"],
                "title": "WeatherData",
                "type": "object",
            }
        )
        result = await client.call_tool("get_weather", {"city": "London"})
        assert result.structured_content == {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}


async def test_dataclass_produces_the_same_schema() -> None:
    """tutorial004: a dataclass (an annotated class) produces the same object schema again."""
    async with Client(tutorial004.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema == snapshot(
            {
                "properties": {
                    "temperature": {"title": "Temperature", "type": "number"},
                    "humidity": {"title": "Humidity", "type": "number"},
                    "conditions": {"title": "Conditions", "type": "string"},
                },
                "required": ["temperature", "humidity", "conditions"],
                "title": "WeatherData",
                "type": "object",
            }
        )
        result = await client.call_tool("get_weather", {"city": "London"})
        assert result.structured_content == {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}


async def test_list_return_is_wrapped() -> None:
    """tutorial005: `-> list[WeatherData]` is wrapped in `{"result": ...}` and flattened into one block per item."""
    async with Client(tutorial005.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema == snapshot(
            {
                "$defs": {
                    "WeatherData": {
                        "properties": {
                            "temperature": {"title": "Temperature", "type": "number"},
                            "humidity": {"title": "Humidity", "type": "number"},
                            "conditions": {"title": "Conditions", "type": "string"},
                        },
                        "required": ["temperature", "humidity", "conditions"],
                        "title": "WeatherData",
                        "type": "object",
                    }
                },
                "properties": {
                    "result": {"items": {"$ref": "#/$defs/WeatherData"}, "title": "Result", "type": "array"}
                },
                "required": ["result"],
                "title": "get_forecastOutput",
                "type": "object",
            }
        )
        result = await client.call_tool("get_forecast", {"city": "London", "days": 2})
        assert result.structured_content == {
            "result": [
                {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"},
                {"temperature": 17.2, "humidity": 0.83, "conditions": "Overcast"},
            ]
        }
        assert len(result.content) == 2


async def test_dict_str_return_is_not_wrapped() -> None:
    """tutorial006: `dict[str, float]` is already a JSON object, so there is no `result` wrapper."""
    async with Client(tutorial006.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema == snapshot(
            {"additionalProperties": {"type": "number"}, "title": "get_temperaturesDictOutput", "type": "object"}
        )
        result = await client.call_tool("get_temperatures", {"cities": ["London", "Reykjavik"]})
        assert result.structured_content == {"London": 16.2, "Reykjavik": 4.4}


async def test_return_value_is_validated_against_the_schema(caplog: pytest.LogCaptureFixture) -> None:
    """tutorial007: a return value that does not match the output schema is a tool error, not a result;
    the field name goes to the server log, not the client."""
    caplog.set_level(logging.ERROR, logger="mcp.server.mcpserver.server")
    async with Client(tutorial007.mcp) as client:
        result = await client.call_tool("get_weather", {"city": "London"})
        assert result.is_error
        assert result.structured_content is None
        assert result.content == [TextContent(type="text", text="Error executing tool get_weather")]
    (record,) = [r for r in caplog.records if r.name == "mcp.server.mcpserver.server"]
    assert record.getMessage() == "Tool 'get_weather' raised an unexpected exception"
    assert record.exc_info is not None and record.exc_info[1] is not None
    assert "1 validation error for WeatherData\nhumidity\n  Field required" in str(record.exc_info[1].__cause__)


async def test_structured_output_false_opts_out() -> None:
    """tutorial008: `structured_output=False` drops the schema and the structured channel entirely."""
    async with Client(tutorial008.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema is None
        result = await client.call_tool("weather_report", {"city": "London"})
        assert result.structured_content is None
        assert result.content == [
            TextContent(type="text", text="London: 17 degrees, overcast, light rain easing by evening.")
        ]


async def test_content_blocks_and_media_are_opted_out_of_structured_output() -> None:
    """The "Content blocks and media" section: a content-block or `Image`/`Audio` return annotation, bare or
    as list items, derives no output schema and no structured content; the blocks are the result."""
    mcp = MCPServer("Reports")
    document = EmbeddedResource(
        type="resource", resource=TextResourceContents(uri="report://q3", mime_type="text/markdown", text="# Q3")
    )

    @mcp.tool()
    def report() -> EmbeddedResource:
        return document

    @mcp.tool()
    def chart() -> list[str | Image]:
        return ["Sales by region:", Image(data=b"png", format="png")]

    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert tools["report"].output_schema is None
        assert tools["chart"].output_schema is None
        report_result = await client.call_tool("report", {})
        assert (report_result.content, report_result.structured_content) == ([document], None)
        chart_result = await client.call_tool("chart", {})
        assert chart_result.structured_content is None
        assert chart_result.content == [
            TextContent(type="text", text="Sales by region:"),
            ImageContent(type="image", data="cG5n", mime_type="image/png"),
        ]


async def test_class_without_type_hints_is_silently_unstructured() -> None:
    """tutorial009: a class with no annotations on its body gets no schema, and the model gets a `repr`."""
    async with Client(tutorial009.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema is None
        result = await client.call_tool("get_station", {"name": "north"})
        assert not result.is_error
        assert result.structured_content is None
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text.startswith('"<docs_src.structured_output.tutorial009.Station object at 0x')


def test_structured_output_true_makes_the_silence_an_error() -> None:
    """tutorial009: `structured_output=True` refuses a return type it cannot build a schema for."""
    mcp = MCPServer("Weather")
    with pytest.raises(InvalidSignature, match="is not serializable for structured output"):
        mcp.add_tool(tutorial009.get_station, structured_output=True)
