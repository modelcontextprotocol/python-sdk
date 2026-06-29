"""`docs/tutorial/structured-output.md`: every claim the page makes, proved against the real SDK."""

import pytest
from inline_snapshot import snapshot
from mcp_types import TextContent

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
from mcp.server.mcpserver.exceptions import InvalidSignature

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_scalar_return_is_wrapped() -> None:
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
    """`list[WeatherData]` is wrapped in `result` and flattened into one content block per item."""
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
    async with Client(tutorial006.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema == snapshot(
            {"additionalProperties": {"type": "number"}, "title": "get_temperaturesDictOutput", "type": "object"}
        )
        result = await client.call_tool("get_temperatures", {"cities": ["London", "Reykjavik"]})
        assert result.structured_content == {"London": 16.2, "Reykjavik": 4.4}


async def test_return_value_is_validated_against_the_schema() -> None:
    async with Client(tutorial007.mcp) as client:
        result = await client.call_tool("get_weather", {"city": "London"})
        assert result.is_error
        assert result.structured_content is None
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text.startswith("Error executing tool get_weather: 1 validation error for WeatherData")
        assert "humidity\n  Field required" in result.content[0].text


async def test_structured_output_false_opts_out() -> None:
    async with Client(tutorial008.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema is None
        result = await client.call_tool("weather_report", {"city": "London"})
        assert result.structured_content is None
        assert result.content == [
            TextContent(type="text", text="London: 17 degrees, overcast, light rain easing by evening.")
        ]


async def test_class_without_type_hints_is_silently_unstructured() -> None:
    async with Client(tutorial009.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema is None
        result = await client.call_tool("get_station", {"name": "north"})
        assert not result.is_error
        assert result.structured_content is None
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text.startswith('"<docs_src.structured_output.tutorial009.Station object at 0x')


def test_structured_output_true_makes_the_silence_an_error() -> None:
    mcp = MCPServer("Weather")
    with pytest.raises(InvalidSignature, match="is not serializable for structured output"):
        mcp.add_tool(tutorial009.get_station, structured_output=True)
