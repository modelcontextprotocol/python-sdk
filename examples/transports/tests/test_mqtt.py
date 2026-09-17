import aiomqtt
import pytest

from mcp_transport_examples.mqtt import mqtt_transport


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("incoming", "outgoing", "expiry", "size"),
    [
        ("same", "same", 60, 4096),
        ("bad/#", "response", 60, 4096),
        ("request", "bad/+", 60, 4096),
        ("request", "response", 0, 4096),
        ("request", "response", 2**32, 4096),
        ("request", "response", 60, 0),
    ],
)
async def test_invalid_configuration_fails_without_connecting(
    incoming: str, outgoing: str, expiry: int, size: int
) -> None:
    """Adapter-defined constraints reject unsafe topic routing and limits before touching a broker."""
    client = aiomqtt.Client("unused.invalid", protocol=aiomqtt.ProtocolVersion.V5)
    with pytest.raises(ValueError):
        async with mqtt_transport(
            client, incoming_topic=incoming, outgoing_topic=outgoing, expiry=expiry, max_message_size=size
        ):
            raise NotImplementedError
