from pathlib import Path

from mcp.server.experimental.ai_catalog import server_card_entry
from mcp.shared.experimental.ai_catalog import AICatalog
from mcp.shared.experimental.server_card import Remote, ServerCard

# A card can be built directly, without a running server — useful for
# publishing it as a static file behind any web server or CDN.
card = ServerCard(
    name="com.example/dice-roller",
    version="1.0.0",
    description="Rolls dice for tabletop games.",
    title="Dice Roller",
    remotes=[Remote(type="streamable-http", url="https://dice.example.com/mcp")],
)
catalog = AICatalog(
    spec_version="1.0",
    entries=[server_card_entry(card, "https://dice.example.com/server-card.json")],
)

# `by_alias=True` emits the wire names (`$schema`, `_meta`, `type`);
# `exclude_none=True` drops unset optional fields.
card_json = card.model_dump_json(by_alias=True, exclude_none=True)
catalog_json = catalog.model_dump_json(by_alias=True, exclude_none=True)


def write_static_site(directory: Path) -> None:
    """Write the card and the well-known catalog under `directory`."""
    (directory / "server-card.json").write_text(card_json)
    well_known = directory / ".well-known"
    well_known.mkdir(parents=True, exist_ok=True)
    (well_known / "ai-catalog.json").write_text(catalog_json)
