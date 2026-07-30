"""Public server APIs keep runtime-evaluable type hints.

The HTTP transport and auth stacks load lazily (see AGENTS.md "Import cost"), so their
types are not module globals of the server modules. Every SDK-owned type a public
signature names is instead spelled so that `typing.get_type_hints()` can still resolve
it at runtime: through the web-framework-free `mcp.server.event_store` /
`mcp.server.transport_security` modules, or through the lazy `mcp.server` namespace.
Only the starlette-owned annotations of the HTTP app builders (`Starlette`, `Route`)
stay typing-only, which `docs/migration.md` documents.
"""

import sys
import typing

from mcp.server.auth.provider import OAuthAuthorizationServerProvider, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.event_store import EventStore
from mcp.server.lowlevel import Server
from mcp.server.mcpserver import MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings


def test_lazily_loaded_sdk_types_resolve_in_public_method_hints():
    """SDK-defined: the event-store, transport-security, auth and session-manager
    annotations evaluate at runtime to the very classes users import."""
    run_http = typing.get_type_hints(MCPServer.run_streamable_http_async)
    assert typing.get_args(run_http["event_store"])[0] is EventStore
    assert typing.get_args(run_http["transport_security"])[0] is TransportSecuritySettings
    run_sse = typing.get_type_hints(MCPServer.run_sse_async)
    assert typing.get_args(run_sse["transport_security"])[0] is TransportSecuritySettings

    init = typing.get_type_hints(MCPServer.__init__)
    assert typing.get_args(init["auth"])[0] is AuthSettings
    assert typing.get_args(init["token_verifier"])[0] is TokenVerifier
    assert typing.get_origin(typing.get_args(init["auth_server_provider"])[0]) is OAuthAuthorizationServerProvider

    for cls in (Server, MCPServer):
        prop = vars(cls)["session_manager"]
        assert isinstance(prop, property)
        assert typing.get_type_hints(prop.fget)["return"] is StreamableHTTPSessionManager


def test_sdk_owned_names_in_the_app_builder_signatures_still_evaluate():
    """SDK-defined: in the app builders (whose full hints are typing-only because of the
    starlette return/route types), every SDK-owned parameter annotation still evaluates
    against the module namespace, exactly as `get_type_hints` would evaluate it."""
    method = Server.streamable_http_app
    namespace = vars(sys.modules[method.__module__])

    def _probe() -> None:
        """Carries the SDK-owned subset of the app builder's annotations."""

    _probe.__annotations__ = {
        name: method.__annotations__[name]
        for name in ("event_store", "transport_security", "auth", "token_verifier", "auth_server_provider")
    }
    resolved = typing.get_type_hints(_probe, globalns=namespace)
    assert typing.get_args(resolved["event_store"])[0] is EventStore
    assert typing.get_args(resolved["transport_security"])[0] is TransportSecuritySettings
    assert typing.get_args(resolved["auth"])[0] is AuthSettings
    assert typing.get_args(resolved["token_verifier"])[0] is TokenVerifier
    assert typing.get_origin(typing.get_args(resolved["auth_server_provider"])[0]) is OAuthAuthorizationServerProvider
