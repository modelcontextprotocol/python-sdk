from pathlib import Path

from mcp.shared.experimental.server_card import Remote, ServerCard

card = ServerCard(
    name="com.example/weather",
    version="1.4.0",
    description="Hourly forecasts.",
    title="Weather",
    website_url="https://example.com",
    remotes=[Remote(type="streamable-http", url="https://mcp.example.com/mcp")],
)


def publish(path: Path) -> None:
    path.write_text(card.model_dump_json(by_alias=True, exclude_none=True))
