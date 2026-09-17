import pytest
from aio_pika import Channel, Connection
from yarl import URL

from mcp_transport_examples.amqp import amqp_transport


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("incoming", "outgoing", "expiry", "size", "confirms"),
    [
        ("", "responses", 60, 4096, True),
        ("requests", "", 60, 4096, True),
        ("same", "same", 60, 4096, True),
        ("requests", "responses", 0, 4096, True),
        ("requests", "responses", 60, 0, True),
        ("requests", "responses", 60, 4096, False),
    ],
)
async def test_invalid_configuration_fails_without_connecting(
    incoming: str, outgoing: str, expiry: int, size: int, confirms: bool
) -> None:
    """Adapter-defined constraints reject unsafe queue routing and limits before touching a broker."""
    connection = Connection(URL("amqp://unused.invalid"))
    channel = Channel(connection, publisher_confirms=confirms)
    with pytest.raises(ValueError):
        async with amqp_transport(
            channel, incoming_queue=incoming, outgoing_queue=outgoing, expiry=expiry, max_message_size=size
        ):
            raise NotImplementedError
