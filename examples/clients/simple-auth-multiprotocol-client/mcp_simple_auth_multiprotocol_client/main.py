#!/usr/bin/env python3
"""Multi-protocol MCP client: API Key + Mutual TLS (placeholder)."""

import asyncio
import os
from typing import Any

import httpx
from mcp.client.auth.multi_protocol import MultiProtocolAuthProvider, TokenStorage
from mcp.client.auth.protocol import AuthContext, AuthProtocol
from mcp.client.auth.registry import AuthProtocolRegistry
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import (
    APIKeyCredentials,
    AuthCredentials,
    AuthProtocolMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)


class InMemoryStorage(TokenStorage):
    """In-memory credential storage."""

    def __init__(self) -> None:
        self._creds: AuthCredentials | None = None

    async def get_tokens(self) -> AuthCredentials | OAuthToken | None:
        return self._creds

    async def set_tokens(self, tokens: AuthCredentials | OAuthToken) -> None:
        self._creds = tokens if isinstance(tokens, AuthCredentials) else None


class ApiKeyProtocol:
    """AuthProtocol implementation for API Key (X-API-Key header)."""

    protocol_id = "api_key"
    protocol_version = "1.0"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        return APIKeyCredentials(protocol_id=self.protocol_id, api_key=self._api_key)

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        if isinstance(credentials, APIKeyCredentials):
            request.headers["X-API-Key"] = credentials.api_key

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        return isinstance(credentials, APIKeyCredentials) and bool(credentials.api_key.strip())

    async def discover_metadata(
        self,
        metadata_url: str | None,
        prm: ProtectedResourceMetadata | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> AuthProtocolMetadata | None:
        return None


class MutualTlsPlaceholderProtocol:
    """Placeholder for Mutual TLS; when selected, raises (no client cert in this example)."""

    protocol_id = "mutual_tls"
    protocol_version = "1.0"

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        raise RuntimeError("Mutual TLS not implemented in this example. Use API Key (set MCP_API_KEY or default).")

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        pass

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        return False

    async def discover_metadata(
        self,
        metadata_url: str | None,
        prm: ProtectedResourceMetadata | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> AuthProtocolMetadata | None:
        return None


def _register_protocols() -> None:
    AuthProtocolRegistry.register("api_key", ApiKeyProtocol)
    AuthProtocolRegistry.register("mutual_tls", MutualTlsPlaceholderProtocol)


class SimpleAuthMultiprotocolClient:
    """MCP client with multi-protocol auth (API Key + mTLS placeholder)."""

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url
        self.session: ClientSession | None = None

    async def connect(self) -> None:
        _register_protocols()
        api_key = os.getenv("MCP_API_KEY", "demo-api-key-12345")
        storage = InMemoryStorage()
        protocols: list[AuthProtocol] = [
            ApiKeyProtocol(api_key=api_key),
            MutualTlsPlaceholderProtocol(),
        ]
        auth = MultiProtocolAuthProvider(
            server_url=self.server_url.rstrip("/").replace("/mcp", ""),
            storage=storage,
            protocols=protocols,
        )
        async with httpx.AsyncClient(auth=auth, follow_redirects=True) as http_client:
            async with streamable_http_client(
                url=self.server_url,
                http_client=http_client,
            ) as (read_stream, write_stream, get_session_id):
                await self._run_session(read_stream, write_stream, get_session_id)

    async def _run_session(self, read_stream: Any, write_stream: Any, get_session_id: Any) -> None:
        print("Initializing MCP session...")
        async with ClientSession(read_stream, write_stream) as session:
            self.session = session
            await session.initialize()
            print("Session initialized.")
            if get_session_id:
                sid = get_session_id()
                if sid:
                    print(f"Session ID: {sid}")
            await self._interactive_loop()

    async def list_tools(self) -> None:
        if not self.session:
            print("Not connected.")
            return
        try:
            result = await self.session.list_tools()
            if hasattr(result, "tools") and result.tools:
                print("\nTools:")
                for t in result.tools:
                    print(f"  - {t.name}")
            else:
                print("No tools.")
        except Exception as e:
            print(f"List tools failed: {e}")

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> None:
        if not self.session:
            print("Not connected.")
            return
        try:
            result = await self.session.call_tool(name, arguments or {})
            if hasattr(result, "content"):
                for c in result.content:
                    if getattr(c, "type", None) == "text":
                        print(getattr(c, "text", c))
                    else:
                        print(c)
            else:
                print(result)
        except Exception as e:
            print(f"Call tool failed: {e}")

    async def _interactive_loop(self) -> None:
        print("\nCommands: list | call <tool> [args] | quit\n")
        while True:
            try:
                line = input("mcp> ").strip()
                if not line:
                    continue
                if line == "quit":
                    break
                if line == "list":
                    await self.list_tools()
                elif line.startswith("call "):
                    parts = line.split(maxsplit=2)
                    tool = parts[1] if len(parts) > 1 else ""
                    if not tool:
                        print("Specify tool name.")
                        continue
                    args: dict[str, Any] = {}
                    if len(parts) > 2:
                        import json

                        try:
                            args = json.loads(parts[2])
                        except json.JSONDecodeError:
                            pass
                    await self.call_tool(tool, args)
                else:
                    print("Unknown command.")
            except (KeyboardInterrupt, EOFError):
                break
        print("Bye.")


async def main() -> None:
    server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8002/mcp")
    print(f"Connecting to {server_url}...")
    client = SimpleAuthMultiprotocolClient(server_url)
    try:
        await client.connect()
    except Exception as e:
        print(f"Failed: {e}")
        raise


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
