"""Drop from `Client` to `client.session`: the `ClientSession` mechanics layer beneath."""

from mcp import types
from mcp.client import Client, ClientSession
from stories._harness import connect_from_args, run_client


async def scenario(client: Client) -> None:
    # client.session is the ClientSession that Client.__aenter__ connected for you.
    session: ClientSession = client.session

    # __aenter__ ran exactly one of initialize() / discover() / adopt(), so exactly one
    # era-specific result slot is populated — whichever era was negotiated.
    assert (session.initialize_result is None) != (session.discover_result is None)

    # ClientSession's accessors are Optional (None until a result is adopted); Client's
    # same-named properties narrow them to non-Optional inside the `async with` block.
    assert session.protocol_version is not None
    assert session.protocol_version == client.protocol_version
    assert session.server_info == client.server_info
    assert session.server_capabilities == client.server_capabilities

    # send_request() is the generic primitive every typed client.*() method wraps:
    # any ClientRequest model + the expected result type.
    listed = await session.send_request(types.ListToolsRequest(), types.ListToolsResult)
    assert [t.name for t in listed.tools] == ["add"]

    # The typed wrapper produces the same result.
    assert await client.list_tools() == listed


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__))
