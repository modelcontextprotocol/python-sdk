#!/usr/bin/env python3
"""
Simple MCP client example with OAuth authentication support.

This client connects to an MCP server using streamable HTTP transport with OAuth.

"""

import asyncio
import json
import os
import threading
import time
import webbrowser
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp.client.auth import (
    OAuthClientProvider,
    discover_oauth_metadata,
)
from mcp.client.oauth_auth import OAuthAuth
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


class CallbackHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler to capture OAuth callback."""

    authorization_code = None
    state = None
    error = None

    def do_GET(self):
        """Handle GET request from OAuth redirect."""
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)

        if "code" in query_params:
            CallbackHandler.authorization_code = query_params["code"][0]
            CallbackHandler.state = query_params.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html>
            <body>
                <h1>Authorization Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
                <script>setTimeout(() => window.close(), 2000);</script>
            </body>
            </html>
            """)
        elif "error" in query_params:
            CallbackHandler.error = query_params["error"][0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"""
            <html>
            <body>
                <h1>Authorization Failed</h1>
                <p>Error: {query_params['error'][0]}</p>
                <p>You can close this window and return to the terminal.</p>
            </body>
            </html>
            """.encode()
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


class CallbackServer:
    """Simple server to handle OAuth callbacks."""

    def __init__(self, port=3000):
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        """Start the callback server in a background thread."""
        self.server = HTTPServer(("localhost", self.port), CallbackHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"🖥️  Started callback server on http://localhost:{self.port}")

    def stop(self):
        """Stop the callback server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1)

    def wait_for_callback(self, timeout=300):
        """Wait for OAuth callback with timeout."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if CallbackHandler.authorization_code:
                return CallbackHandler.authorization_code
            elif CallbackHandler.error:
                raise Exception(f"OAuth error: {CallbackHandler.error}")
            time.sleep(0.1)
        raise Exception("Timeout waiting for OAuth callback")


class JsonSerializableOAuthClientMetadata(OAuthClientMetadata):
    """OAuth client metadata that handles JSON serialization properly."""

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Override to ensure URLs are serialized as strings and exclude null values."""
        # Exclude null values by default
        kwargs.setdefault("exclude_none", True)
        data = super().model_dump(**kwargs)

        # Convert AnyHttpUrl objects to strings
        if "redirect_uris" in data:
            data["redirect_uris"] = [str(url) for url in data["redirect_uris"]]

        # Debug: print what we're sending
        print(f"🐛 Client metadata being sent: {json.dumps(data, indent=2)}")
        return data


class SimpleOAuthProvider(OAuthClientProvider):
    """Simple OAuth client provider for demonstration purposes."""

    def __init__(self, server_url: str, callback_port: int = 3000):
        self._callback_port = callback_port
        self._redirect_uri = f"http://localhost:{callback_port}/callback"
        self._server_url = server_url
        self._callback_server = None
        print(f"🐛 OAuth provider initialized with redirect URI: {self._redirect_uri}")
        # Store the raw data for easy serialization - scope will be updated dynamically
        self._client_metadata_dict = {
            "client_name": "Simple Auth Client",
            "redirect_uris": [self._redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",  # Use client secret
            "scope": "read",  # Default scope, will be updated
        }
        self._client_info: OAuthClientInformationFull | None = None
        self._tokens: OAuthToken | None = None
        self._code_verifier: str | None = None
        self._authorization_code: str | None = None
        self._metadata_discovered = False

    @property
    def redirect_url(self) -> str:
        return self._redirect_uri

    async def _discover_and_update_metadata(self):
        """Discover server OAuth metadata and update client scope accordingly."""
        if self._metadata_discovered:
            return

        try:
            print("🐛 Discovering OAuth metadata...")
            metadata = await discover_oauth_metadata(self._server_url)
            if metadata and metadata.scopes_supported:
                scope = " ".join(metadata.scopes_supported)
                self._client_metadata_dict["scope"] = scope
                print(f"🐛 Updated scope to: {scope}")
            self._metadata_discovered = True
        except Exception as e:
            print(f"🐛 Failed to discover metadata: {e}, using default scope")
            self._metadata_discovered = True

    @property
    def client_metadata(self) -> OAuthClientMetadata:
        # Create a fresh instance each time using our custom serializable version
        return JsonSerializableOAuthClientMetadata.model_validate(
            self._client_metadata_dict
        )

    async def client_information(self) -> OAuthClientInformationFull | None:
        return self._client_info

    async def save_client_information(
        self, client_information: OAuthClientInformationFull
    ) -> None:
        self._client_info = client_information
        print(f"Saved client information: {client_information.client_id}")

    async def tokens(self) -> OAuthToken | None:
        return self._tokens

    async def save_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens
        print(f"Saved OAuth tokens: {tokens.access_token[:10]}...")

    async def redirect_to_authorization(self, authorization_url: str) -> None:
        # Start callback server
        self._callback_server = CallbackServer(self._callback_port)
        self._callback_server.start()

        print("\n🌐 Opening authorization URL in your default browser...")
        print(f"URL: {authorization_url}")
        webbrowser.open(authorization_url)

        print("⏳ Waiting for authorization callback...")
        print("(Complete the authorization in your browser)")

        try:
            # Wait for the callback with authorization code
            authorization_code = self._callback_server.wait_for_callback(timeout=300)
            print(f"✅ Received authorization code: {authorization_code[:20]}...")

            # Store the authorization code so auth() can handle token exchange
            self._authorization_code = authorization_code
            print("🎉 OAuth callback received successfully!")

        except Exception as e:
            print(f"❌ OAuth flow failed: {e}")
            raise
        finally:
            # Always stop the callback server
            if self._callback_server:
                self._callback_server.stop()
                self._callback_server = None

    async def save_code_verifier(self, code_verifier: str) -> None:
        self._code_verifier = code_verifier

    async def code_verifier(self) -> str:
        if self._code_verifier is None:
            raise ValueError("No code verifier available")
        return self._code_verifier


class SimpleAuthClient:
    """Simple MCP client with auth support."""

    def __init__(self, server_url: str):
        self.server_url = server_url
        # Extract base URL for auth server (remove /mcp endpoint for auth endpoints)
        auth_server_url = server_url.replace("/mcp", "")
        # Use default redirect URI - this is where the auth server will redirect the user
        # The user will need to copy the authorization code from this callback URL
        self.auth_provider = SimpleOAuthProvider(auth_server_url)
        self.session: ClientSession | None = None

    async def connect(self):
        """Connect to the MCP server."""
        print(f"🔗 Attempting to connect to {self.server_url}...")

        try:
            # Set up callback server
            callback_server = CallbackServer(port=3000)
            callback_server.start()

            async def callback_handler() -> tuple[str, str | None]:
                """Wait for OAuth callback and return auth code and state."""
                print("⏳ Waiting for authorization callback...")
                try:
                    auth_code = callback_server.wait_for_callback(timeout=300)
                    return auth_code, CallbackHandler.state
                finally:
                    callback_server.stop()

            # Create OAuth authentication handler using the new interface
            oauth_auth = OAuthAuth(
                server_url=self.server_url.replace("/mcp", ""),
                client_metadata=self.auth_provider.client_metadata,
                storage=None,  # Use in-memory storage
                redirect_handler=None,  # Use default (open browser)
                callback_handler=callback_handler,
            )

            # Initialize the auth handler and ensure we have tokens

            # Create streamable HTTP transport with auth handler
            stream_context = streamablehttp_client(
                url=self.server_url,
                auth=oauth_auth,
                timeout=timedelta(seconds=60),
            )

            print(
                "📡 Opening transport connection (HTTPX handles auth automatically)..."
            )
            async with stream_context as (read_stream, write_stream, get_session_id):
                print("🤝 Initializing MCP session...")
                async with ClientSession(read_stream, write_stream) as session:
                    self.session = session
                    print("⚡ Starting session initialization...")
                    await session.initialize()
                    print("✨ Session initialization complete!")

                    print(f"\n✅ Connected to MCP server at {self.server_url}")
                    session_id = get_session_id()
                    if session_id:
                        print(f"Session ID: {session_id}")

                    # Run interactive loop
                    await self.interactive_loop()

        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            import traceback

            traceback.print_exc()

    async def list_tools(self):
        """List available tools from the server."""
        if not self.session:
            print("❌ Not connected to server")
            return

        try:
            result = await self.session.list_tools()
            if hasattr(result, "tools") and result.tools:
                print("\n📋 Available tools:")
                for i, tool in enumerate(result.tools, 1):
                    print(f"{i}. {tool.name}")
                    if tool.description:
                        print(f"   Description: {tool.description}")
                    print()
            else:
                print("No tools available")
        except Exception as e:
            print(f"❌ Failed to list tools: {e}")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None):
        """Call a specific tool."""
        if not self.session:
            print("❌ Not connected to server")
            return

        try:
            result = await self.session.call_tool(tool_name, arguments or {})
            print(f"\n🔧 Tool '{tool_name}' result:")
            if hasattr(result, "content"):
                for content in result.content:
                    if content.type == "text":
                        print(content.text)
                    else:
                        print(content)
            else:
                print(result)
        except Exception as e:
            print(f"❌ Failed to call tool '{tool_name}': {e}")

    async def interactive_loop(self):
        """Run interactive command loop."""
        print("\n🎯 Interactive MCP Client")
        print("Commands:")
        print("  list - List available tools")
        print("  call <tool_name> [args] - Call a tool")
        print("  quit - Exit the client")
        print()

        while True:
            try:
                command = input("mcp> ").strip()

                if not command:
                    continue

                if command == "quit":
                    break

                elif command == "list":
                    await self.list_tools()

                elif command.startswith("call "):
                    parts = command.split(maxsplit=2)
                    tool_name = parts[1] if len(parts) > 1 else ""

                    if not tool_name:
                        print("❌ Please specify a tool name")
                        continue

                    # Parse arguments (simple JSON-like format)
                    arguments = {}
                    if len(parts) > 2:
                        import json

                        try:
                            arguments = json.loads(parts[2])
                        except json.JSONDecodeError:
                            print("❌ Invalid arguments format (expected JSON)")
                            continue

                    await self.call_tool(tool_name, arguments)

                else:
                    print(
                        "❌ Unknown command. Try 'list', 'call <tool_name>', or 'quit'"
                    )

            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break
            except EOFError:
                break


async def main():
    """Main entry point."""
    # Default server URL - can be overridden with environment variable
    # Most MCP streamable HTTP servers use /mcp as the endpoint
    server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

    print("🚀 Simple MCP Auth Client")
    print(f"Connecting to: {server_url}")

    # Start connection flow - OAuth will be handled automatically
    client = SimpleAuthClient(server_url)
    await client.connect()


def cli():
    """CLI entry point for uv script."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
