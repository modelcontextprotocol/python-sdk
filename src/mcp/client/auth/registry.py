"""Auth protocol registry.

Provides registration and selection logic for multi-protocol authentication.
"""

from mcp.client.auth.protocol import AuthProtocol


class AuthProtocolRegistry:
    """Registry for auth protocol implementations.

    Stores protocol implementation classes and selects a protocol based on server-declared availability, defaults,
    and preferences.
    """

    _protocols: dict[str, type[AuthProtocol]] = {}

    @classmethod
    def register(cls, protocol_id: str, protocol_class: type[AuthProtocol]) -> None:
        """Register a protocol implementation.

        Args:
            protocol_id: Protocol identifier (e.g. "oauth2", "api_key").
            protocol_class: Class implementing AuthProtocol (not an instance).
        """
        cls._protocols[protocol_id] = protocol_class

    @classmethod
    def get_protocol_class(cls, protocol_id: str) -> type[AuthProtocol] | None:
        """Return a registered protocol class by protocol_id.

        Args:
            protocol_id: Protocol identifier.

        Returns:
            Protocol class, or None if not registered.
        """
        return cls._protocols.get(protocol_id)

    @classmethod
    def select_protocol(
        cls,
        available_protocols: list[str],
        default_protocol: str | None = None,
        preferences: dict[str, int] | None = None,
    ) -> str | None:
        """Select one protocol that the client supports from server-declared available protocols.

        Selection order:
        1. Filter protocols to those registered in the client.
        2. If a default protocol is provided and supported, return it.
        3. If a preference map is provided, sort by ascending preference value and pick the first.
        4. Otherwise return the first supported protocol.

        Args:
            available_protocols: Server-declared available protocol IDs.
            default_protocol: Optional server-recommended default protocol ID.
            preferences: Optional protocol preference mapping (smaller value means higher priority).

        Returns:
            Selected protocol ID, or None if there is no overlap.
        """
        supported = [p for p in available_protocols if p in cls._protocols]
        if not supported:
            return None

        if default_protocol and default_protocol in supported:
            return default_protocol

        if preferences:
            supported.sort(key=lambda p: preferences.get(p, 999))

        return supported[0] if supported else None

    @classmethod
    def list_registered(cls) -> list[str]:
        """Return registered protocol IDs (useful for tests/debugging).

        Returns:
            List of registered protocol IDs.
        """
        return list(cls._protocols.keys())
