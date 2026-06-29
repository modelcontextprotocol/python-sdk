"""Probe server/discover once, persist the result, reconnect with zero round-trips — a fresh `Client` via `targets`."""

from mcp_types import DiscoverResult
from mcp_types.version import LATEST_MODERN_VERSION

from mcp.client import Client
from stories._harness import TargetFactory, run_client


async def main(targets: TargetFactory, *, mode: str = "auto") -> None:
    # mode="auto" probes server/discover inside __aenter__ and caches the result; a hard version pin skips the probe.
    async with Client(targets(), mode=mode) as client:
        discovered = client.session.discover_result
        assert discovered is not None, "mode='auto' against a modern server populates discover_result"
        assert client.protocol_version == LATEST_MODERN_VERSION
        assert client.server_info.name == "reconnect-example"
        assert LATEST_MODERN_VERSION in discovered.supported_versions

        result = await client.call_tool("add", {"a": 2, "b": 3})
        assert result.structured_content == {"result": 5}, result

    # Round-trip through JSON to model loading the result from an on-disk cache.
    saved = discovered.model_dump_json(by_alias=True)
    rehydrated = DiscoverResult.model_validate_json(saved)
    assert rehydrated == discovered

    # Reconnect: a version pin plus prior_discover= adopts the prior state with zero round-trips; a bare pin
    # would synthesize a blank server_info. A Client cannot be re-entered after exit, so targets() yields a fresh one.
    async with Client(targets(), mode=LATEST_MODERN_VERSION, prior_discover=rehydrated) as second:
        assert second.protocol_version == LATEST_MODERN_VERSION
        assert second.server_info.name == "reconnect-example"
        assert second.server_capabilities.tools is not None
        assert second.session.discover_result == rehydrated

        result = await second.call_tool("add", {"a": 1, "b": 1})
        assert result.structured_content == {"result": 2}, result


if __name__ == "__main__":
    run_client(main)
