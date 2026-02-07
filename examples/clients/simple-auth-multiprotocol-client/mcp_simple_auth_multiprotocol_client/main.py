#!/usr/bin/env python3
"""Multi-protocol MCP client: OAuth (with optional DPoP), API Key, Mutual TLS (placeholder)."""

import asyncio
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from mcp.client.auth.multi_protocol import MultiProtocolAuthProvider, TokenStorage
from mcp.client.auth.protocol import AuthContext, AuthProtocol
from mcp.client.auth.protocols.oauth2 import OAuth2Protocol
from mcp.client.auth.registry import AuthProtocolRegistry
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import (
    APIKeyCredentials,
    AuthCredentials,
    AuthProtocolMetadata,
    OAuthClientMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from pydantic import AnyHttpUrl


class InMemoryStorage(TokenStorage):
    """In-memory credential storage supporting both AuthCredentials and OAuthToken.

    Also implements get_client_info/set_client_info for OAuth client registration storage.
    """

    def __init__(self) -> None:
        self._creds: AuthCredentials | OAuthToken | None = None
        self._client_info: Any = None

    async def get_tokens(self) -> AuthCredentials | OAuthToken | None:
        return self._creds

    async def set_tokens(self, tokens: AuthCredentials | OAuthToken) -> None:
        self._creds = tokens

    async def get_client_info(self) -> Any:
        """Get stored OAuth client information."""
        return self._client_info

    async def set_client_info(self, client_info: Any) -> None:
        """Store OAuth client information."""
        self._client_info = client_info


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to capture OAuth callback."""

    def __init__(self, request: Any, client_address: Any, server: Any, callback_data: dict[str, Any]):
        self.callback_data = callback_data
        super().__init__(request, client_address, server)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)
        if "code" in query_params:
            self.callback_data["authorization_code"] = query_params["code"][0]
            self.callback_data["state"] = query_params.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization Successful!</h1><p>You can close this window.</p>")
        elif "error" in query_params:
            self.callback_data["error"] = query_params["error"][0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h1>Error</h1><p>{query_params['error'][0]}</p>".encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Suppress logging


class CallbackServer:
    """Server to handle OAuth callbacks."""

    def __init__(self, port: int = 3031):
        self.port = port
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.callback_data: dict[str, Any] = {"authorization_code": None, "state": None, "error": None}

    def start(self) -> None:
        callback_data = self.callback_data

        class DataHandler(CallbackHandler):
            def __init__(self, request: Any, client_address: Any, server: Any):
                super().__init__(request, client_address, server, callback_data)

        self.server = HTTPServer(("localhost", self.port), DataHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"Callback server started on http://localhost:{self.port}")

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1)

    def wait_for_callback(self, timeout: int = 300) -> str:
        start = time.time()
        while time.time() - start < timeout:
            if self.callback_data["authorization_code"]:
                return self.callback_data["authorization_code"]
            if self.callback_data["error"]:
                raise RuntimeError(f"OAuth error: {self.callback_data['error']}")
            time.sleep(0.1)
        raise RuntimeError("Timeout waiting for OAuth callback")

    def get_state(self) -> str | None:
        return self.callback_data["state"]


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
    AuthProtocolRegistry.register("oauth2", OAuth2Protocol)
    AuthProtocolRegistry.register("api_key", ApiKeyProtocol)
    AuthProtocolRegistry.register("mutual_tls", MutualTlsPlaceholderProtocol)


class SimpleAuthMultiprotocolClient:
    """MCP client with multi-protocol auth (OAuth + DPoP, API Key, mTLS placeholder)."""

    def __init__(self, server_url: str, use_oauth: bool = False, dpop_enabled: bool = False) -> None:
        self.server_url = server_url
        self.use_oauth = use_oauth
        self.dpop_enabled = dpop_enabled
        self.session: ClientSession | None = None

    async def connect(self) -> None:
        _register_protocols()
        storage = InMemoryStorage()
        protocols: list[AuthProtocol] = []

        callback_server: CallbackServer | None = None

        if self.use_oauth:
            # Setup OAuth with optional DPoP
            callback_server = CallbackServer(port=3031)
            callback_server.start()

            async def callback_handler() -> tuple[str, str | None]:
                print("Waiting for OAuth authorization...")
                try:
                    code = callback_server.wait_for_callback(timeout=300)
                    return code, callback_server.get_state()
                finally:
                    callback_server.stop()

            async def redirect_handler(url: str) -> None:
                print(f"Opening browser for authorization: {url}")
                webbrowser.open(url)

            client_metadata = OAuthClientMetadata(
                client_name="Multi-protocol Auth Client",
                redirect_uris=[AnyHttpUrl("http://localhost:3031/callback")],
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
            )

            oauth_protocol = OAuth2Protocol(
                client_metadata=client_metadata,
                redirect_handler=redirect_handler,
                callback_handler=callback_handler,
                dpop_enabled=self.dpop_enabled,
            )
            protocols.append(oauth_protocol)
            print(f"OAuth protocol enabled (DPoP: {self.dpop_enabled})")

        # Add non-OAuth protocols. Allow forcing protocol injection for integration tests.
        forced = os.getenv("MCP_AUTH_PROTOCOL", "").strip().lower()
        if forced in ("mutual_tls", "mtls"):
            # Force mTLS placeholder to be selectable (do not inject API key fallback).
            protocols.append(MutualTlsPlaceholderProtocol())
        else:
            # Default: API key (from env) plus mTLS placeholder as fallback.
            api_key = os.getenv("MCP_API_KEY", "demo-api-key-12345")
            protocols.append(ApiKeyProtocol(api_key=api_key))
            protocols.append(MutualTlsPlaceholderProtocol())

        try:
            # Create http_client first, then pass it to auth provider
            # This allows OAuth discovery to work (requires http_client for PRM fetch)
            async with httpx.AsyncClient(follow_redirects=True) as http_client:
                auth = MultiProtocolAuthProvider(
                    server_url=self.server_url.rstrip("/").replace("/mcp", ""),
                    storage=storage,
                    protocols=protocols,
                    http_client=http_client,
                    dpop_enabled=self.dpop_enabled,
                )
                # Set auth on client after creation
                http_client.auth = auth

                async with streamable_http_client(
                    url=self.server_url,
                    http_client=http_client,
                ) as (read_stream, write_stream):
                    await self._run_session(read_stream, write_stream)
        finally:
            if callback_server:
                callback_server.stop()

    async def _run_session(self, read_stream: Any, write_stream: Any) -> None:
        print("Initializing MCP session...")
        async with ClientSession(read_stream, write_stream) as session:
            self.session = session
            await session.initialize()
            print("Session initialized.")
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
    use_oauth = os.getenv("MCP_USE_OAUTH", "").lower() in ("1", "true", "yes")
    dpop_enabled = os.getenv("MCP_DPOP_ENABLED", "").lower() in ("1", "true", "yes")

    print(f"Connecting to {server_url}...")
    print(f"  OAuth: {'enabled' if use_oauth else 'disabled'}")
    print(f"  DPoP: {'enabled' if dpop_enabled else 'disabled'}")

    if dpop_enabled and not use_oauth:
        print("  Warning: DPoP requires OAuth enabled (MCP_USE_OAUTH=1) to take effect")

    client = SimpleAuthMultiprotocolClient(server_url, use_oauth=use_oauth, dpop_enabled=dpop_enabled)
    try:
        await client.connect()
    except Exception as e:
        print(f"Failed: {e}")
        raise


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
