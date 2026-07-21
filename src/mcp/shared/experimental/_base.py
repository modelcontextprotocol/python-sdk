"""Internals shared by the experimental Server Card and AI Catalog modules."""

import ipaddress

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

SERVER_CARD_NAME_PATTERN = r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$"
"""Reverse-DNS namespace, one slash, then the server name (`com.example/weather`)."""


class CardModel(BaseModel):
    """Base for all card and catalog models.

    The wire format is camelCase and the schema objects are open, so extra
    (vendor) fields must survive a parse and re-serialize round trip.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")


def is_loopback_host(host: str) -> bool:
    """Whether `host` is `localhost` or a loopback IP literal (`127.0.0.0/8`, `::1`)."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False
